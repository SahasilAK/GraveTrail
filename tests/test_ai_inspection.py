import json

import httpx
import pytest
from test_ai_extraction_recovery import envelope
from test_ai_extraction_recovery import setup_run as _setup_run

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import run_analysis
from dataforge.connections import RuntimeConnections


def setup_run(*args, **kwargs):
    store, workspace = _setup_run(*args, **kwargs)
    store.set_setting(workspace, 'llm_history', True)
    return store, workspace


def test_existing_history_privacy_setting_prevents_payload_retention(tmp_path):
    from dataforge.ai_inspection import inspection_items, inspection_payload
    store, workspace = _setup_run(tmp_path, files=1)
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'),
        transport=httpx.MockTransport(lambda request: httpx.Response(400, content=b'private-error')))
    ticket = inspection_items(store, workspace, result.run_id)['items'][0]['attempt_id']
    assert 'disabled' in inspection_payload(store, workspace, result.run_id, ticket, 'output')['status']
    assert not store.rows('SELECT content FROM ai_inspection_artifacts WHERE content IS NOT NULL')
    store.close()


def test_capture_matches_actual_wire_body_and_response_and_survives_reopen(tmp_path):
    from dataforge.ai_inspection import inspection_items, inspection_payload
    from dataforge.store import Store
    store, workspace = setup_run(tmp_path, files=1)
    bodies, outputs = [], []
    def provider(request):
        bodies.append(request.content.decode())
        body = json.loads(json.loads(request.content)['messages'][-1]['content'])
        response = envelope([{'part_id': item['part']['part_id'], 'coverage': 'no_operations'} for item in body['items']])
        outputs.append(response.content.decode())
        return response
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    items = inspection_items(store, workspace, result.run_id)
    assert items['total'] == 1
    item = items['items'][0]
    assert item['request_id'] and item['attempt_id'] and item['work_kind'] == 'extraction'
    for kind, expected in [('input', bodies[0]), ('output', outputs[0])]:
        payload = inspection_payload(store, workspace, result.run_id, item['attempt_id'], kind)
        assert payload['content'] == expected
        assert payload['status'] == 'retained' and payload['redacted'] is False
    decoded = inspection_payload(store, workspace, result.run_id, item['attempt_id'], 'decoded')
    assert json.loads(decoded['content'])['validated']
    store.close()
    store = Store(tmp_path)
    assert inspection_payload(store, workspace, result.run_id, item['attempt_id'], 'output')['content'] == outputs[0]
    with pytest.raises(ValueError):
        inspection_payload(store, 'other', result.run_id, item['attempt_id'], 'output')
    store.close()


def test_capture_redacts_credentials_without_altering_dispatch(tmp_path):
    from dataforge.ai_inspection import inspection_items, inspection_payload
    store, workspace = setup_run(tmp_path, files=1)
    manager = RuntimeConnections()
    manager.register('DATAFORGE_CAPTURE_KEY', 'synthetic-capture-credential')
    config = json.loads(store.rows('SELECT config FROM llm_profiles')[0]['config'])
    config['key_env'] = 'DATAFORGE_CAPTURE_KEY'
    from dataforge.llm import Profile
    from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
    profile = Profile.model_validate(config)
    profile.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=70000, source='manual'), profile)
    store.execute('UPDATE llm_profiles SET config=?', [profile.model_dump_json()])
    observed = []
    def provider(request):
        assert request.headers['authorization'] == 'Bearer synthetic-capture-credential'
        observed.append(request.content.decode())
        return httpx.Response(400, content=b'{"api_key":"unknown-sensitive-value","error":"synthetic-capture-credential"}')
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'), connections=manager,
                          transport=httpx.MockTransport(provider))
    item = inspection_items(store, workspace, result.run_id)['items'][0]
    output = inspection_payload(store, workspace, result.run_id, item['attempt_id'], 'output')
    assert output['redacted'] and '[REDACTED]' in output['content']
    assert 'synthetic-capture-credential' not in output['content']
    assert 'unknown-sensitive-value' not in output['content']
    assert inspection_payload(store, workspace, result.run_id, item['attempt_id'], 'input')['content'] == observed[0]
    store.close()


def test_shorter_workspace_retention_and_disabling_history_remove_bodies(tmp_path):
    from time import time

    from dataforge.ai_analysis_store import save_run
    from dataforge.ai_inspection import capture_payload, cleanup_payloads, inspection_payload
    from dataforge.ai_pipeline_store import begin_attempt, save_request
    store, workspace = setup_run(tmp_path, files=0)
    store.set_setting(workspace, 'llm_retention_days', 1)
    save_run(store, workspace, 'r', mode='ai', status='cancelled')
    save_request(store, workspace, 'r', 'q', [])
    ticket = begin_attempt(store, workspace, 'r', 'q', 100)
    capture_payload(store, workspace, 'r', ticket, 'output', b'response')
    store.execute('UPDATE ai_inspection_artifacts SET captured_at=?', [time() - 2 * 86400])
    assert 'expired' in inspection_payload(store, workspace, 'r', ticket, 'output')['status']
    cleanup_payloads(store, workspace)
    assert store.rows('SELECT content FROM ai_inspection_artifacts')[0]['content'] is None
    capture_payload(store, workspace, 'r', ticket, 'output', b'new-response')
    store.set_setting(workspace, 'llm_history', False)
    assert 'disabled' in inspection_payload(store, workspace, 'r', ticket, 'output')['status']
    cleanup_payloads(store, workspace)
    assert store.rows('SELECT content FROM ai_inspection_artifacts')[0]['content'] is None
    store.close()
