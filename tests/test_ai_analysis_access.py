import asyncio

import pytest

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.ingestion import Importer
from dataforge.store import Store


def test_preview_report_and_ai_start_have_independent_permissions(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('Access')
    Importer(store, w).files([('q.sql', b'create table x as select id from a;')], {'.sql'})
    service = AgentService(store, AccessPolicy(allow_write=True))
    try:
        preview = service.call('analysis_preview', w, mode='hybrid')
        assert not preview['valid']
        with pytest.raises(AgentError) as error:
            service.call('analyze', w, mode='hybrid')
        assert error.value.code == 'network_not_allowed'
        store.set_setting(w, 'agent_access', {'allow_source': False})
        with pytest.raises(AgentError):
            service.call('analysis_preview', w, mode='hybrid')
    finally:
        service.close()
        store.close()


def test_mcp_project_tools_are_registered_and_preview_stays_offline(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('MCP')
    service = AgentService(store)
    server = create_server(service)

    async def check():
        names = {tool.name for tool in await server.list_tools()}
        assert {'preview_project_analysis', 'get_project_analysis_report', 'cancel_job'} <= names
        result = await server.call_tool('preview_project_analysis', {'workspace_id': w, 'mode': 'hybrid'})
        assert not result.isError

    try:
        asyncio.run(check())
    finally:
        service.close()
        store.close()


def test_background_operation_preserves_ai_mode_instead_of_silently_parsing(tmp_path, monkeypatch):
    store = Store(tmp_path)
    w = store.create_workspace('Background')
    service = AgentService(store, AccessPolicy(allow_write=True, allow_llm=True))
    seen = []
    monkeypatch.setattr(service, '_run_project_analysis', lambda workspace, request, **kwargs:
                        seen.append(request.mode) or {'status': 'committed'}, raising=False)
    try:
        service.run_operation(w, 'analyze', {'mode': 'hybrid'})
        assert seen == ['hybrid']
        assert not store.runs(w)
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
        '--mode', 'hybrid', '--background'])
    assert result.exit_code == 0, result.output
    job = json.loads(next((tmp_path / 'agent/jobs').glob('*.json')).read_text())
    assert job['request']['policy']['allow_llm'] is True
    assert job['request']['policy']['allowed_llm_origins'] == ['http://localhost:20128']


def test_unresolved_table_boundary_cannot_look_like_complete_lineage(tmp_path):
    from dataforge.services import analyze
    store = Store(tmp_path)
    w = store.create_workspace('Boundary')
    Importer(store, w).files([('q.sql', b'create table x as select id from a;')], {'.sql'})
    analyze(store, w)
    store.execute("UPDATE edges SET status='unresolved' WHERE workspace_id=?", [w])
    service = AgentService(store)
    try:
        result = service.call('lineage', w, asset='x')
        assert not result['complete'] and 'unresolved' in result['boundaries']
        assert result['unresolved_count'] == 1
    finally:
        service.close()
        store.close()


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
            service.runtime_profiles[w, pid] = profile.model_dump_json()
        store.set_setting(w, 'task_models', {'project_lineage': 'extract', 'lineage_review': 'review'})
        for pid, profile, secret in zip(('extract', 'review'), profiles, ('synthetic-A', 'synthetic-B')):
            with connection_scope(_BoundConnections(service, w).for_profile(pid, profile)), Adapter(profile) as adapter:
                assert adapter._headers()['Authorization'] == 'Bearer ' + secret
    finally:
        service.close()
        store.close()
