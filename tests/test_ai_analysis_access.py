
import pytest

from dataforge.agent.contracts import AccessPolicy, AgentError
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
