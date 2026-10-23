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


def test_mcp_project_tools_are_registered_and_preview_stays_offline(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('MCP')
    service = AgentService(store)
    server = create_server(service)

    async def check():
        names = {tool.name for tool in await server.list_tools()}
        assert {'preview_project_analysis', 'get_project_analysis_report', 'cancel_job'} <= names
        result = await server.call_tool('preview_project_analysis', {'workspace_id': w, 'mode': 'ai'})
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
        service.run_operation(w, 'analyze', {'mode': 'ai'})
        assert seen == ['ai']
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
        '--mode', 'ai', '--background'])
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
            from dataforge.model_capabilities import runtime_profile
            service.runtime_profiles[w, pid] = runtime_profile(profile)
        store.set_setting(w, 'task_models', {'project_lineage': 'extract', 'lineage_review': 'review'})
        for pid, profile, secret in zip(('extract', 'review'), profiles, ('synthetic-A', 'synthetic-B')):
            with connection_scope(_BoundConnections(service, w).for_profile(pid, profile)), Adapter(profile) as adapter:
                assert adapter._headers()['Authorization'] == 'Bearer ' + secret
    finally:
        service.close()
        store.close()


def test_actual_mcp_http_sdk_previews_offline_and_builds_one_shared_path(tmp_path, monkeypatch):
    import json
    from datetime import timedelta
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from dataforge.agent.mcp_server import http_app
    from test_ai_resumable_files import configured, empty_provider
    store = Store(tmp_path)
    w = store.create_workspace('SDK')
    Importer(store, w).files([('q.sql', b'select 1; select 2;')], {'.sql'})
    configured(store, w)
    service = AgentService(store, AccessPolicy(workspaces=(w,), allow_write=True, allow_llm=True,
        allowed_llm_origins=('http://localhost:1234',)))
    calls = []
    service.provider_transport = httpx.MockTransport(empty_provider(calls))
    token = 'synthetic-sdk-token-' + 'x' * 40
    monkeypatch.setenv('DATAFORGE_MCP_TOKEN', token)
    server = create_server(service)
    application = http_app(server, service.policy)
    async def check():
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), headers={'Authorization': 'Bearer ' + token}) as client:
                async with streamable_http_client('http://127.0.0.1:8765/mcp', http_client=client) as (read, write, _):
                    async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=20)) as session:
                        await session.initialize()
                        preview = await session.call_tool('preview_project_analysis', {'workspace_id': w})
                        assert not preview.isError
                        assert preview.structuredContent['estimated_requests'] == 1
                        assert not calls
                        job = await session.call_tool('start_lineage_analysis', {'workspace_id': w, 'mode': 'ai'})
                        assert not job.isError
                        for _ in range(100):
                            status = await session.call_tool('get_job_status', {'workspace_id': w, 'job_id': job.structuredContent['job_id']})
                            if status.structuredContent['status'] in {'completed', 'failed'}:
                                break
                            await asyncio.sleep(.02)
                        assert status.structuredContent['result']['status'] == 'committed', status
        assert len(calls) == 1
    try:
        asyncio.run(check())
    finally:
        service.close()
        store.close()
