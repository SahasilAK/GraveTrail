import json

import httpx
import pytest
from test_ai_resumable_files import configured, empty_provider
from test_ai_token_budget import model

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_budget import allocate_analysis_profile, request_budget
from dataforge.analysis_service import preview_analysis, run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


def automatic(context=70000, **caps):
    return model(context, **caps).model_copy(update={'output_mode': 'automatic'})


def test_preview_execution_pins_allocation_and_requests_have_no_history(tmp_path):
    from dataforge.ai_analysis_store import load_file_extractions

    store = Store(tmp_path)
    w = store.create_workspace('allocation wire')
    configured(store, w, automatic())
    Importer(store, w).files([(f'{i}.sql', b'select 1;' + b' ' * 9000) for i in range(10)], {'.sql'})
    request = AnalysisRequest(mode='ai', output_share=30)
    preview = preview_analysis(store, w, request)
    assert preview['valid'] and preview['allocation']['output_allowance'] == 19950
    calls, seen = [], []
    good = empty_provider(seen)
    def provider(r):
        body = json.loads(r.content)
        calls.append(body)
        assert body['max_tokens'] == preview['allocation']['output_allowance']
        assert [m['role'] for m in body['messages']] == ['system', 'user']
        assert not {'previous_response_id', 'conversation', 'conversation_id'} & body.keys()
        assert request_budget(allocate_analysis_profile(automatic(), request)[0],
                              json.dumps(body, ensure_ascii=False, separators=(',', ':')), body['max_tokens']).fits
        return good(r)
    report = run_analysis(store, w, request, transport=httpx.MockTransport(provider))
    assert report.status == 'committed'
    assert len(calls) > 1 and any(len(json.loads(b['messages'][1]['content'])['items']) > 1 for b in calls)
    parts = [i['part']['part_id'] for b in calls for i in json.loads(b['messages'][1]['content'])['items']]
    assert len(parts) == len(set(parts)) == 10
    assert len(load_file_extractions(store, w, report.run_id)) == 10
    summary = json.loads(store.rows('SELECT summary FROM ai_analysis_runs')[0]['summary'])
    assert summary['allocation'] == preview['allocation']
    for packing in preview['packing']:
        assert packing['files'] and packing['parts'] and packing['stop_reasons']
        assert packing['estimated_input_tokens'] <= packing['input_allowance']
    store.close()


def test_saved_allocation_is_pinned_on_resume_and_legacy_checkpoint_keeps_budget(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    from dataforge.llm import Profile
    from dataforge.model_capabilities import execution_profile
    store = Store(tmp_path)
    w = store.create_workspace('budget resume')
    p = model()
    configured(store, w, p)
    Importer(store, w).files([('q.sql', b'select 1;')], {'.sql'})
    planner = service.plan_file_consolidation
    def stopped(*args, **kwargs):
        raise ValueError('synthetic_before_publication')
    monkeypatch.setattr(service, 'plan_file_consolidation', stopped)
    first = run_analysis(store, w, AnalysisRequest(mode='ai', output_share=40), transport=httpx.MockTransport(empty_provider([])))
    assert first.status == 'failed'
    changed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id, output_share=50))
    assert changed.status == 'blocked' and changed.reasons == ['Continuation token allocation is pinned']
    summary = json.loads(store.rows('SELECT summary FROM ai_analysis_runs WHERE run_id=?', [first.run_id])[0]['summary'])
    for key in ('budget_policy', 'output_share', 'input_token_limit', 'output_token_limit'):
        summary['request'].pop(key, None)
    summary['pin']['profile'] = service._hash(execution_profile(Profile.model_validate_json(p.model_dump_json())))
    summary.pop('allocation', None)
    store.execute('UPDATE ai_analysis_runs SET summary=? WHERE run_id=?', [json.dumps(summary), first.run_id])
    store.close()
    store = Store(tmp_path)
    monkeypatch.setattr(service, 'plan_file_consolidation', planner)
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id),
        transport=httpx.MockTransport(lambda r: pytest.fail('Saved extraction was resent')))
    assert resumed.status == 'committed', resumed.reasons
    final = json.loads(store.rows('SELECT summary FROM ai_analysis_runs WHERE run_id=?', [first.run_id])[0]['summary'])
    assert final['allocation']['policy'] == 'legacy' and final['allocation']['output_allowance'] == 8000
    store.close()
