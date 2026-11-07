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


@pytest.mark.parametrize('status,content', [(200, b'{broken-json'), (400, b'{"error":"bad parameters"}')])
def test_malformed_and_error_responses_are_retained(tmp_path, status, content):
    from dataforge.ai_inspection import inspection_items, inspection_payload
    store, workspace = setup_run(tmp_path, files=1)
    result = run_analysis(store, workspace, AnalysisRequest(mode='ai'),
        transport=httpx.MockTransport(lambda request: httpx.Response(status, content=content)))
    items = inspection_items(store, workspace, result.run_id)
    assert items['total'] == (3 if status == 200 else 1), 'Malformed bodies use the existing three bounded recovery passes'
    for item in items['items']:
        assert inspection_payload(store, workspace, result.run_id, item['attempt_id'], 'output')['content'] == content.decode()
        assert item['status'] == 'known_failure'
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


def test_retries_unknown_and_planned_attempts_have_distinct_payloads(tmp_path):
    from dataforge.ai_inspection import inspection_items, inspection_payload
    store, workspace = setup_run(tmp_path, files=1)
    calls = []
    def provider(request):
        calls.append(request.content.decode())
        raise httpx.ReadTimeout('lost')
    first = run_analysis(store, workspace, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(provider))
    item = inspection_items(store, workspace, first.run_id)['items'][0]
    assert item['status'] == 'unknown'
    assert inspection_payload(store, workspace, first.run_id, item['attempt_id'], 'input')['content'] == calls[0]
    assert inspection_payload(store, workspace, first.run_id, item['attempt_id'], 'output')['status'] == 'Not retained'
    second = run_analysis(store, workspace, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(provider))
    assert second.run_id == first.run_id and len(calls) == 1
    from dataforge.ai_pipeline_store import save_request
    save_request(store, workspace, first.run_id, 'planned', ['p'])
    planned = inspection_items(store, workspace, first.run_id)['items'][-1]
    assert planned['attempt_id'] is None and planned['status'] == 'planned'
    store.close()


def test_migration_and_backup_restore_include_separate_payloads(tmp_path):
    from dataforge.ai_analysis_store import save_run
    from dataforge.ai_inspection import capture_payload, inspection_payload
    from dataforge.ai_pipeline_store import begin_attempt, save_request
    from dataforge.database_maintenance import backup, restore_backup
    from dataforge.store import Store
    home = tmp_path / 'old'
    store = Store(home)
    workspace = store.create_workspace('small')
    store.set_setting(workspace, 'llm_history', True)
    store.execute('DROP TABLE ai_inspection_artifacts')
    store.execute('DELETE FROM schema_migrations WHERE version=10')
    store.close()
    store = Store(home)
    assert store.rows('SELECT max(version) AS v FROM schema_migrations')[0]['v'] == 10
    save_run(store, workspace, 'r', mode='ai', status='cancelled')
    save_request(store, workspace, 'r', 'q', [])
    ticket = begin_attempt(store, workspace, 'r', 'q', 100)
    capture_payload(store, workspace, 'r', ticket, 'output', b'captured')
    archive = backup(store)
    store.close()
    restored = tmp_path / 'restored'
    restore_backup(archive, restored)
    store = Store(restored)
    assert inspection_payload(store, workspace, 'r', ticket, 'output')['content'] == 'captured'
    store.close()


def test_production_async_io_path_captures_exact_body_and_cancels_while_waiting(tmp_path, monkeypatch):
    import asyncio
    import threading

    from dataforge.agent.jobs import Jobs
    from dataforge.ai_analysis_progress import analysis_progress
    from dataforge.ai_inspection import inspection_items, inspection_payload
    store, workspace = setup_run(tmp_path, files=1)
    entered, stopped = threading.Event(), threading.Event()
    bodies = []
    async def provider(request):
        bodies.append(request.content.decode())
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client(transport=httpx.MockTransport(provider), **kwargs))
    jobs = Jobs(tmp_path)
    try:
        job = jobs.start(workspace, 'ai_analysis', lambda progress, cancelled: run_analysis(
            store, workspace, AnalysisRequest(mode='ai'), progress=progress, cancelled=cancelled).model_dump(), cancellable=True)
        assert entered.wait(10)
        record = jobs.read(job['job_id'], workspace)
        item = inspection_items(store, workspace, record['run_id'])['items'][0]
        assert inspection_payload(store, workspace, record['run_id'], item['attempt_id'], 'input')['content'] == bodies[0]
        jobs.cancel(job['job_id'], workspace)
        assert jobs.wait(job['job_id'], workspace, timeout=5)['status'] == 'cancelled'
        assert stopped.wait(2) and len(bodies) == 1
        assert analysis_progress(store, workspace, record['run_id'])['attempts']['unknown'] == 1
        assert inspection_payload(store, workspace, record['run_id'], item['attempt_id'], 'output')['status'] == 'Not retained'
    finally:
        jobs.close()
        store.close()


def test_retention_pagination_historical_missing_and_workspace_cleanup(tmp_path, monkeypatch):
    import dataforge.ai_inspection as inspection
    from dataforge.ai_analysis_store import save_run
    from dataforge.ai_pipeline_store import begin_attempt, save_request
    store, workspace = setup_run(tmp_path, files=0)
    save_run(store, workspace, 'r', mode='ai', status='cancelled')
    save_request(store, workspace, 'r', 'q', ['p'])
    tickets = [begin_attempt(store, workspace, 'r', 'q', 100) for _ in range(3)]
    assert inspection.inspection_payload(store, workspace, 'r', tickets[0], 'input')['status'] == 'Not retained'
    assert inspection.inspection_items(store, workspace, 'r', offset=1, limit=1)['items'][0]['attempt_id'] == tickets[1]
    monkeypatch.setattr(inspection, 'MAX_ARTIFACT_BYTES', 10)
    inspection.capture_payload(store, workspace, 'r', tickets[0], 'input', b'x' * 11)
    assert 'limit' in inspection.inspection_payload(store, workspace, 'r', tickets[0], 'input', limit=10)['status']
    monkeypatch.setattr(inspection, 'MAX_ARTIFACT_BYTES', 100000)
    monkeypatch.setattr(inspection, 'MAX_RUN_BYTES', 40)
    inspection.capture_payload(store, workspace, 'r', tickets[0], 'input', b'a' * 30)
    inspection.capture_payload(store, workspace, 'r', tickets[1], 'input', b'b' * 30)
    assert 'limit' in inspection.inspection_payload(store, workspace, 'r', tickets[1], 'input')['status']
    page = inspection.inspection_payload(store, workspace, 'r', tickets[0], 'input', offset=7, limit=10)
    assert page['content'] == 'a' * 10 and page['total_chars'] == 30 and page['has_more']
    store.execute('UPDATE ai_inspection_artifacts SET captured_at=0')
    inspection.cleanup_payloads(store, workspace)
    assert 'expired' in inspection.inspection_payload(store, workspace, 'r', tickets[0], 'input')['status']
    from dataforge.cleanup import apply_cleanup, cleanup_plan
    preview = cleanup_plan(store, workspace, 'ai')
    name = store.rows('SELECT name FROM workspaces WHERE workspace_id=?', [workspace])[0]['name']
    apply_cleanup(store, preview, confirmation=name)
    assert not store.rows('SELECT * FROM ai_inspection_artifacts')
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
