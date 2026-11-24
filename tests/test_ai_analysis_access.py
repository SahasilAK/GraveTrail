
import asyncio

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.ai_analysis_store import save_run
from dataforge.ai_inspection import capture_payload
from dataforge.ai_pipeline_store import begin_attempt, save_request
from dataforge.cli import app
from dataforge.ingestion import Importer
from dataforge.store import Store


def test_inspect_project_attempts_with_current_source_and_retention_policy(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('Inspection')
    other = store.create_workspace('Other')
    store.set_setting(w, 'llm_history', True)
    save_run(store, w, 'run', mode='ai', status='cancelled')
    save_request(store, w, 'run', 'sent', ['part'], details={'work_kind': 'extract'})
    save_request(store, w, 'run', 'planned', ['other'])
    ticket = begin_attempt(store, w, 'run', 'sent', 100)
    capture_payload(store, w, 'run', ticket, 'output', b'retained-output')
    service = AgentService(store)
    try:
        server = create_server(service)

        def call(tool, **args):
            return asyncio.run(server.call_tool(tool, {'workspace_id': w, **args}))

        runs = call('list_project_analysis_runs')
        assert not runs.isError and runs.structuredContent['items'][0]['run_id'] == 'run'
        listing = call('list_project_analysis_attempts', run_id='run', options={'limit': 1})
        assert not listing.isError and listing.structuredContent['items'][0]['attempt_id'] == ticket
        planned = call('list_project_analysis_attempts', run_id='run', offset=1)
        assert not planned.isError and planned.structuredContent['items'][0]['attempt_id'] is None
        args = {'run_id': 'run', 'attempt_id': ticket, 'kind': 'output'}
        page = call('get_project_analysis_attempt_content', **args, offset=8, length=3)
        assert not page.isError and page.structuredContent['content'] == '-ou'
        denied = asyncio.run(server.call_tool('get_project_analysis_attempt_content', {'workspace_id': other, **args}))
        assert denied.isError
        store.set_setting(w, 'llm_history', False)
        assert call('get_project_analysis_attempt_content', **args).structuredContent['content'] is None
        store.set_setting(w, 'agent_access', {'allow_source': False})
        forbidden = call('get_project_analysis_attempt_content', **args)
        assert forbidden.isError and forbidden.structuredContent['error']['code'] == 'forbidden'
        store.set_setting(w, 'agent_access', {'allow_source': True})
        store.set_setting(w, 'llm_history', True)
    finally:
        service.close()
        store.close()
    runner = CliRunner()
    destination = tmp_path / 'response.txt'
    args = ['--home', str(tmp_path), '--json', 'lineage', 'analysis-attempt-content', 'run', ticket, '-w', w,
            '--length', '3', '--destination', str(destination)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0 and destination.read_bytes() == b'retained-output', result.output
    destination.write_bytes(b'keep these bytes')
    assert runner.invoke(app, args).exit_code != 0
    assert destination.read_bytes() == b'keep these bytes'


def test_preview_report_and_ai_start_have_independent_permissions(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('Access')
    Importer(store, w).files([('q.sql', b'create table x as select id from a;')], {'.sql'})
    service = AgentService(store, AccessPolicy(allow_write=True))
    try:
        preview = service.call('analysis_preview', w, mode='ai')
        assert not preview['valid']
        with pytest.raises(AgentError) as error:
            service.call('analyze', w, mode='ai')
        assert error.value.code == 'network_not_allowed'
        store.set_setting(w, 'agent_access', {'allow_source': False})
        with pytest.raises(AgentError):
            service.call('analysis_preview', w, mode='ai')
    finally:
        service.close()
        store.close()


def test_detached_cli_journal_keeps_grants_but_no_credentials(tmp_path, monkeypatch):
    import json

    from typer.testing import CliRunner

    from dataforge.cli import app
    store = Store(tmp_path)
    w = store.create_workspace('Detached')
    store.close()
    monkeypatch.setattr('subprocess.Popen', lambda *a, **kwargs: None)
    result = CliRunner().invoke(app, ['--home', str(tmp_path), '--json', '--allow-write', '--allow-llm',
        '--allowed-llm-origin', 'http://localhost:20128', 'lineage', 'build', '-w', w,
        '--mode', 'ai', '--background'])
    assert result.exit_code == 0, result.output
    job = json.loads(next((tmp_path / 'agent/jobs').glob('*.json')).read_text())
    assert job['request']['policy']['allow_llm'] is True
    assert job['request']['policy']['allowed_llm_origins'] == ['http://localhost:20128']


def test_profile_specific_credentials_never_cross_extraction_and_review(tmp_path):
    from dataforge.connections import RuntimeConnections, connection_scope
    from dataforge.llm import Adapter, Profile
    from dataforge.project_analysis import _BoundConnections
    store = Store(tmp_path)
    w = store.create_workspace('Credential isolation')
    service = AgentService(store)
    try:
        profiles = [Profile(provider='OpenAI compatible', base_url=f'http://localhost:{port}',
                            model='test', key_env='DATAFORGE_SHARED_KEY') for port in (1234, 1235)]
        for pid, profile, secret in zip(('extract', 'review'), profiles, ('synthetic-A', 'synthetic-B')):
            store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', [pid, w, pid, profile.model_dump_json()])
            manager = RuntimeConnections()
            manager.register('DATAFORGE_RUNTIME_CREDENTIAL', secret)
            service.runtime_connections[w, pid] = manager
            from dataforge.model_capabilities import runtime_profile
            service.runtime_profiles[w, pid] = runtime_profile(profile)
        store.set_setting(w, 'task_models', {'project_lineage': 'extract', 'lineage_review': 'review'})
        for pid, profile, secret in zip(('extract', 'review'), profiles, ('synthetic-A', 'synthetic-B')):
            with connection_scope(_BoundConnections(service, w).for_profile(pid, profile)), Adapter(profile) as adapter:
                assert adapter._headers()['Authorization'] == 'Bearer ' + secret
    finally:
        service.close()
        store.close()
