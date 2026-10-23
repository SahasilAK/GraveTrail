import json

import httpx

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.ai_analysis_store import load_file_extractions
from dataforge.analysis_service import run_analysis
from dataforge.ingestion import Importer
from dataforge.store import Store
from test_ai_token_budget import model


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
    def fail(*args):
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
