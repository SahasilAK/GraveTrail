import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from focused_test_profiles import focused_profile

from dataforge.agent.contracts import AccessPolicy, AgentError, AgentSettings
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_ai_offline_preview_grounded_request_merge_and_revoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that ai offline preview grounded request merge and revoke.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    store = Store(tmp_path)
    w = store.create_workspace('AI')
    code = 'create table mart.x as select id from raw.a;'
    Importer(store, w).files([('q.sql', code.encode())], {'.sql'})
    analyze(store, w)
    fid = store.files(w)[0]['file_id']
    p = focused_profile(provider='Ollama', base_url='http://localhost:11434', model='manual')
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['profile', w, 'test', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'profile')
    service = AgentService(store, AccessPolicy(allow_write=True, allow_llm=True, allowed_llm_origins=('http://localhost:11434',)))
    try:
        preview = service.call('ai_chunks', w, file_id=fid, first=1, last=1, task='sql_lineage')
        digest = preview['content_hash']
        payload = {'claims': [{'source': 'raw.a', 'target': 'mart.x', 'operation': 'CREATE', 'start_line': 1,
            'end_line': 1, 'quote': code, 'explanation': 'Explicit source and target', 'confidence': .99}]}
        service.provider_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={'message': {'content': json.dumps(payload)}}))
        server = create_server(service)
        from dataforge.provider_service import authorize_provider
        def reassigned_after_authorization(*args):
            authorize_provider(*args)
            store.set_setting(w, 'default_job', 'reassigned')
        with monkeypatch.context() as changed:
            changed.setattr('dataforge.ai_service.authorize_provider', reassigned_after_authorization)
            stale = asyncio.run(server.call_tool('request_ai_assistance', {'workspace_id': w, 'file_id': fid,
                'first': 1, 'last': 1, 'task': 'sql_lineage', 'expected_hash': digest}))
            assert stale.isError, 'A changed job must be refused before transmission'
            assert not store.rows('SELECT * FROM llm_records')
        store.set_setting(w, 'default_job', 'workspace')
        result = asyncio.run(server.call_tool('request_ai_assistance', {'workspace_id': w, 'file_id': fid,
            'first': 1, 'last': 1, 'task': 'sql_lineage', 'expected_hash': digest}))
        assert not result.isError, result
        rid = result.structuredContent['record_id']
        assert result.structuredContent['outcome'] == 'validated'
        import threading
        def refresh_with_concurrent_read(store: Any, workspace: Any) -> Any:
            """Handle refresh with concurrent read for the test scenario.

            Args:
                store: Store instance exercised by the test.
                workspace: Workspace used by the test.

            Returns:
                Value produced for the test scenario.
            """
            read = threading.Event()
            def read_store() -> None:
                """Handle read store for the test scenario."""
                store.files(workspace)
                read.set()
            thread = threading.Thread(target=read_store, daemon=True)
            thread.start()
            assert read.wait(1), 'Refresh holds the store lock while waiting for analysis'
            thread.join()
            return analyze(store, workspace)
        monkeypatch.setattr('dataforge.ai_service.analyze', refresh_with_concurrent_read)
        first = service.call('ai_merge', w, record_id=rid)
        second = service.call('ai_merge', w, record_id=rid)
        assert first['merged'] == 1 and second['already_merged']
        assert not first['refresh_required'] and not second['refresh_required']
        assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 1
        AgentSettings(allow_source=False).save(store, w)
        metadata = service.call('ai_result', w, record_id=rid)
        assert code not in json.dumps(metadata)
        with pytest.raises(AgentError):
            service.call('ai_result', w, record_id=rid, options={'detail_level': 'detailed'})
    finally:
        service.close()
        store.close()


def test_fallback_uses_its_own_approved_credential(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that fallback uses its own approved credential.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    store = Store(tmp_path)
    w = store.create_workspace('fallback audience')
    Importer(store, w).files([('a.sql', b'create table mart.x as select id from raw.a;')], {'.sql'})
    analyze(store, w)
    source = store.files(w)[0]
    monkeypatch.setenv('DATAFORGE_FIRST_KEY', 'first-profile-canary')
    monkeypatch.setenv('DATAFORGE_SECOND_KEY', 'second-profile-canary')
    for pid, ref in [('first', 'DATAFORGE_FIRST_KEY'), ('second', 'DATAFORGE_SECOND_KEY')]:
        profile = focused_profile(provider='OpenAI compatible', base_url='http://localhost:1234/v1', model=pid, key_env=ref, retries=0)
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', [pid, w, pid, profile.model_dump_json()])
    store.set_setting(w, 'default_profile', 'first')
    store.set_setting(w, 'fallback_profiles', ['second'])
    service = AgentService(store, AccessPolicy(allow_write=True, allow_llm=True,
        allowed_llm_origins=('http://localhost:1234',), allowed_credential_refs=('DATAFORGE_FIRST_KEY', 'DATAFORGE_SECOND_KEY')))
    headers = []
    def respond(request: pytest.FixtureRequest) -> Any:
        """Handle respond for the test scenario.

        Args:
            request: Pytest fixture describing the active test request.

        Returns:
            Value produced for the test scenario.
        """
        headers.append(request.headers['Authorization'])
        if len(headers) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"claims":[]}'}}]})
    service.provider_transport = httpx.MockTransport(respond)
    try:
        service.call('ai_request', w, file_id=source['file_id'], first=1, last=1, task='sql_lineage', expected_hash=source['content_hash'])
        assert headers == ['Bearer first-profile-canary', 'Bearer second-profile-canary']
    finally:
        service.close()
        store.close()


@pytest.mark.parametrize('task', ['sql_lineage', 'sas_lineage', 'lineage_validation', 'column_usage', 'code_explanation'])
def test_all_five_tasks_through_actual_mcp_handler(tmp_path: Path, task: str) -> None:
    """Verify that all five tasks through actual mcp handler.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        task: Task value used by the test case.
    """
    from typer.testing import CliRunner

    from dataforge.cli import app
    store = Store(tmp_path)
    w = store.create_workspace(task)
    code = 'data mart.x;\nset raw.a;\nrun;' if task == 'sas_lineage' else 'create table mart.x as select a.id from raw.a a;'
    extension = '.sas' if task == 'sas_lineage' else '.sql'
    Importer(store, w).files([('a' + extension, code.encode())], {extension})
    analyze(store, w)
    source = store.files(w)[0]
    citation = {'start_line': 1, 'end_line': source['line_count'], 'quote': code}
    if task == 'column_usage':
        payload = {'columns': [{**citation, 'source': 'raw.a', 'column': 'id', 'context': 'SELECT', 'explanation': 'Projection', 'confidence': .9}]}
    elif task == 'code_explanation':
        payload = {'explanations': [{**citation, 'text': 'Direct projection creates mart.x from raw.a.', 'assets': ['raw.a', 'mart.x']}]}
    else:
        payload = {'claims': [{**citation, 'source': 'raw.a', 'target': 'mart.x', 'operation': 'DATA' if task == 'sas_lineage' else 'CREATE', 'explanation': 'Direct input/output', 'confidence': .9}]}
    profile = focused_profile(provider='Ollama', base_url='http://localhost:11434', model='mock')
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'p', profile.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    service = AgentService(store, AccessPolicy(allow_write=True, allow_llm=True, allowed_llm_origins=('http://localhost:11434',)))
    service.provider_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={'message': {'content': '```json\n' + json.dumps(payload) + '\n```'}}))
    try:
        server = create_server(service)
        result = asyncio.run(server.call_tool('request_ai_assistance', {'workspace_id': w, 'file_id': source['file_id'],
            'first': 1, 'last': source['line_count'], 'task': task, 'expected_hash': source['content_hash']}))
        assert not result.isError and result.structuredContent['outcome'] == 'validated', result
        rid = result.structuredContent['record_id']
        detailed = service.call('ai_result', w, record_id=rid, options={'detail_level': 'detailed'})
        assert detailed['details']['content_hash'] == source['content_hash']
        if task in {'column_usage', 'code_explanation'}:
            with pytest.raises(AgentError):
                service.call('ai_merge', w, record_id=rid)
    finally:
        service.close()
        store.close()
    result = CliRunner().invoke(app, ['--home', str(tmp_path), '--json', 'ai', 'chunks', source['file_id'], '-w', w,
        '--first', '1', '--last', str(source['line_count']), '--task', task])
    assert result.exit_code == 0 and json.loads(result.output)['content_hash'] == source['content_hash']
