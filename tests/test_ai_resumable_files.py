import json

import httpx
import pytest
from test_ai_token_budget import model

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_store import load_file_extractions
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store


def configured(store, workspace, profile=None):
    profile = profile or model()
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', workspace, 'mock', profile.model_dump_json()])
    store.set_setting(workspace, 'default_profile', 'p')


def empty_provider(seen):
    def provider(request):
        body = json.loads(request.content)
        context = json.loads(body['messages'][-1]['content'])
        items = []
        for item in context['items']:
            part = item['part']
            seen.append(part['part_id'])
            items.append({'part_id': part['part_id'], 'coverage': 'no_operations'})
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'items': items})},
            'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})
    return provider


def test_unknown_response_requires_acknowledgement_and_durable_ceiling(tmp_path):
    store = Store(tmp_path)
    workspace = store.create_workspace('resume')
    configured(store, workspace)
    Importer(store, workspace).files([('a.sql', b'select 1;')], {'.sql'})
    calls = []
    def lost(request):
        calls.append(1)
        raise httpx.ReadTimeout('unknown')
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai', max_output_tokens_total=8000),
                          transport=httpx.MockTransport(lost))
    assert result.status == 'awaiting_continuation'
    store.close()
    store = Store(tmp_path)
    result2 = run_analysis(store, workspace, AnalysisRequest(mode='ai', resume_run_id=result.run_id),
                           transport=httpx.MockTransport(lost))
    assert result2.reasons == ['unknown_inflight_request_requires_explicit_retry']
    result3 = run_analysis(store, workspace, AnalysisRequest(mode='ai', resume_run_id=result.run_id, retry_unknown=True),
                           transport=httpx.MockTransport(lost))
    assert result3.status == 'awaiting_continuation'
    assert result3.reasons == ['run_output_ceiling_reached']
    assert len(calls) == 1
    store.close()


def test_singleton_and_batch_share_one_pipeline_and_save_final_files(tmp_path):
    store = Store(tmp_path)
    workspace = store.create_workspace('files')
    configured(store, workspace)
    Importer(store, workspace).files([('a.sql', b'select 1;'), ('b.sql', b'select 2;')], {'.sql'})
    seen = []
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(empty_provider(seen)))
    assert result.status == 'committed', result.reasons
    assert len(seen) == len(set(seen)) == 2
    assert len(load_file_extractions(store, workspace, result.run_id)) == 2
    assert result.counts['requests'] == 1
    store.close()


def test_resume_after_extraction_reuses_completed_parts(tmp_path, monkeypatch):
    store = Store(tmp_path)
    workspace = store.create_workspace('stage restart')
    configured(store, workspace)
    Importer(store, workspace).files([('a.sql', b'select 1;')], {'.sql'})
    seen = []
    original = __import__('dataforge.analysis_service', fromlist=['plan_file_consolidation']).plan_file_consolidation
    def fail(*args, **kwargs):
        raise ValueError('synthetic consolidation failure')
    monkeypatch.setattr('dataforge.analysis_service.plan_file_consolidation', fail)
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(empty_provider(seen)))
    assert result.status == 'failed'
    monkeypatch.setattr('dataforge.analysis_service.plan_file_consolidation', original)
    resumed = run_analysis(store, workspace, AnalysisRequest(mode='ai', resume_run_id=result.run_id),
                           transport=httpx.MockTransport(empty_provider(seen)))
    assert resumed.status == 'committed', resumed.reasons
    assert len(seen) == 1
    store.close()


def test_truncated_part_is_split_without_repeating_completed_siblings(tmp_path):
    store = Store(tmp_path)
    workspace = store.create_workspace('truncation')
    configured(store, workspace)
    Importer(store, workspace).files([('a.sql', b'select 1; select 2;')], {'.sql'})
    seen = []
    responder = empty_provider(seen)
    first = [True]
    def provider(request):
        if first[0]:
            first[0] = False
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"items":['}, 'finish_reason': 'length'}]})
        return responder(request)
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    assert result.status == 'committed', result.reasons
    parts = load_file_extractions(store, workspace, result.run_id)[0].part_ids
    assert len(parts) == 2
    assert len(seen) == len(set(seen)) == 2
    store.close()


@pytest.mark.parametrize('stop_after', [1, 2, 3])
def test_cancel_between_part_commits_reopens_and_sends_only_missing(tmp_path, monkeypatch, stop_after):
    import dataforge.analysis_service as service
    from dataforge.ai_analysis_store import load_file_parts
    store = Store(tmp_path)
    w = store.create_workspace('small_sql')
    configured(store, w)
    Importer(store, w).files([(f'{n}.sql', b'select 1;') for n in range(3)], {'.sql'})
    seen, committed = [], []
    original = service.save_part_extraction
    def save(*args, **kwargs):
        original(*args, **kwargs)
        committed.append(args[3].part_id)
    monkeypatch.setattr(service, 'save_part_extraction', save)
    first = run_analysis(store, w, AnalysisRequest(mode='ai'),
        transport=httpx.MockTransport(empty_provider(seen)), cancelled=lambda: len(committed) >= stop_after)
    assert first.status == 'cancelled'
    assert len(load_file_parts(store, w, first.run_id)) == stop_after
    assert not store.rows('SELECT * FROM analysis_runs')
    initial = set(committed)
    requested = set(seen)
    store.close()
    store = Store(tmp_path)
    seen.clear()
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id, retry_unknown=True),
        transport=httpx.MockTransport(empty_provider(seen)))
    assert resumed.status == 'committed', resumed.reasons
    assert set(seen) == requested - initial
    assert len(load_file_parts(store, w, first.run_id)) == 3
    provenance = store.rows("SELECT record_id FROM ai_analysis_units WHERE context_hash='extraction5'")
    assert all(r['record_id'] for r in provenance)
    store.close()


def test_checkpoint_write_failure_blocks_further_dispatch(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store = Store(tmp_path)
    w = store.create_workspace('storage failure')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'select 1;')], {'.sql'})
    def fail(*args, **kwargs):
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(service, 'save_part_extraction', fail)
    seen = []
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(empty_provider(seen)))
    assert result.status == 'failed' and len(seen) == 1
    assert store.rows('SELECT status FROM ai_analysis_requests') == [{'status': 'planned'}]
    assert not store.rows('SELECT * FROM analysis_runs')
    store.close()


def test_interrupted_split_cannot_persist_parent_without_child_plan(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store = Store(tmp_path)
    w = store.create_workspace('atomic split')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'select 1; select 2;')], {'.sql'})
    save = service.save_run
    class ProcessDeath(BaseException):
        pass
    def failed_plan(*args, **kwargs):
        if kwargs.get('summary', {}).get('split_parts'):
            raise ProcessDeath('split plan checkpoint failure')
        return save(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(service, 'save_run', failed_plan)
        with pytest.raises(ProcessDeath):
            run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={'choices':[{'message':{'content':'{"items":['},'finish_reason':'length'}]})))
    store.close()
    store = Store(tmp_path)
    plan = json.loads(store.rows('SELECT summary FROM ai_analysis_runs')[0]['summary'])
    ids = {p['part_id'] for p in plan['parts']}
    for row in store.rows("SELECT result FROM ai_analysis_units WHERE status='superseded'"):
        assert set(json.loads(row['result'])['children']) <= ids
    store.close()
