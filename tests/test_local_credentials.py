import json
from contextlib import closing

import pytest

from dataforge.connections import RuntimeConnections
from dataforge.credentials import CredentialError, NativeCredentials, credential_reference
from dataforge.llm import Profile


class FakeBackend:
    def __init__(self):
        self.values = {}
        self.calls = []
        self.failure = ''

    def get_password(self, service, username):
        self.calls.append(('get', service))
        if self.failure == 'get':
            raise RuntimeError('secret-canary locked')
        return self.values.get((service, username))

    def set_password(self, service, username, secret):
        self.calls.append(('set', service))
        self.values[service, username] = secret
        if self.failure == 'set':
            raise RuntimeError(secret)

    def delete_password(self, service, username):
        self.calls.append(('delete', service))
        if self.failure == 'delete':
            raise RuntimeError('secret-canary')
        self.values.pop((service, username), None)


@pytest.fixture
def vault(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr('dataforge.credentials.approved_backend', lambda: backend)
    return backend


def profile(reference):
    return Profile(provider='Ollama', base_url='http://localhost:11434', model='m', key_env=reference)


def test_session_has_no_persistent_writes_and_no_environment_fallback(tmp_path, vault, monkeypatch):
    p = profile('')
    ref = credential_reference(tmp_path, 'w', 'p', p, saved=False)
    p.key_env = ref
    manager = RuntimeConnections().for_workspace(tmp_path, 'w').for_profile('p', p)
    monkeypatch.setenv(ref, 'wrong-source')
    assert manager.resolve(ref) == ''
    manager.register(ref, 'session-canary')
    assert manager.resolve(ref) == 'session-canary'
    manager.clear(ref)
    assert manager.resolve(ref) == ''
    assert vault.calls == []


def test_saved_survives_manager_and_scopes_recipient(tmp_path, vault, monkeypatch):
    p = profile('')
    ref = NativeCredentials().save(tmp_path, 'w', 'p', p, 'secret-canary')
    p.key_env = ref
    monkeypatch.setenv(ref, 'wrong-source')
    root = RuntimeConnections().for_workspace(tmp_path, 'w')
    assert root.resolve(ref) == ''  # Unbound references never open the vault.
    bound = root.for_profile('p', p)
    assert bound.resolve(ref) == 'secret-canary'
    assert bound.redact('echo secret-canary') == 'echo [REDACTED]'
    for home, workspace, pid, endpoint in [
        (tmp_path / 'other', 'w', 'p', p.base_url), (tmp_path, 'other', 'p', p.base_url),
        (tmp_path, 'w', 'other', p.base_url), (tmp_path, 'w', 'p', 'http://localhost:9999'),
    ]:
        changed = p.model_copy(update={'base_url': endpoint})
        with pytest.raises(CredentialError, match='rebind'):
            RuntimeConnections().for_workspace(home, workspace).for_profile(pid, changed).resolve(ref)
    vault.values.clear()
    assert root.for_profile('p', p).resolve(ref) == ''


def test_failures_are_sanitized_and_failed_save_is_cleaned(tmp_path, vault):
    p = profile('')
    vault.failure = 'set'
    with pytest.raises(CredentialError) as error:
        NativeCredentials().save(tmp_path, 'w', 'p', p, 'secret-canary')
    assert 'secret-canary' not in str(error.value)
    assert not vault.values
    vault.failure = ''
    ref = NativeCredentials().save(tmp_path, 'w', 'p', p, 'secret-canary')
    p.key_env = ref
    vault.failure = 'get'
    with pytest.raises(CredentialError, match='session-only'):
        RuntimeConnections().for_workspace(tmp_path, 'w').for_profile('p', p).resolve(ref)
    vault.failure = 'delete'
    with pytest.raises(CredentialError):
        NativeCredentials().delete(tmp_path, 'w', 'p', p)
    assert vault.values
    assert 'secret-canary' not in json.dumps(vault.calls)


def test_disconnect_does_not_delete_and_requires_explicit_reconnect(tmp_path, vault):
    p = profile('')
    p.key_env = NativeCredentials().save(tmp_path, 'w', 'p', p, 'secret-canary')
    root = RuntimeConnections().for_workspace(tmp_path, 'w')
    root.disconnect(p.key_env)
    assert root.for_profile('p', p).resolve(p.key_env) == ''
    assert vault.values
    root.reconnect(p.key_env)
    assert root.for_profile('p', p).resolve(p.key_env) == 'secret-canary'
    root.register(p.key_env, 'session-override')
    assert root.for_profile('p', p).resolve(p.key_env) == 'session-override'
    assert list(vault.values.values()) == ['secret-canary']
    NativeCredentials().delete(tmp_path, 'w', 'p', p)
    root.clear(p.key_env)
    assert root.for_profile('p', p).resolve(p.key_env) == ''


def saved_profile(store, vault):
    w = store.create_workspace('credentials')
    p = profile('')
    ref = NativeCredentials().save(store.home, w, 'p', p, 'secret-canary')
    p.key_env = p.saved_key_ref = ref
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'test', p.model_dump_json()])
    return w, p


def test_agent_grants_before_vault_reads_and_disconnect(tmp_path, vault):
    import httpx

    from dataforge.agent.contracts import AccessPolicy, AgentError
    from dataforge.agent.service import AgentService
    from dataforge.store import Store

    with closing(Store(tmp_path)) as store:
        w, p = saved_profile(store, vault)
        baseline = list(vault.calls)
        policy = AccessPolicy(allow_write=True, allow_llm=True, allowed_llm_origins=(p.base_url,))
        denied = AgentService(store, policy)
        try:
            assert denied.call('provider_get', w, profile_id='p')['profile']['saved_key_ref'] == ''
            with pytest.raises(AgentError):
                denied.call('provider_models', w, profile_id='p')
            assert vault.calls == baseline
        finally:
            denied.close()
        from dataclasses import replace
        allowed = AgentService(store, replace(policy, allowed_credential_refs=(p.key_env,)))
        def response(request):
            assert request.headers['Authorization'] == 'Bearer secret-canary'
            return httpx.Response(200, json={'models': [{'name': 'echo secret-canary'}]})
        allowed.provider_transport = httpx.MockTransport(response)
        try:
            status = allowed.call('runtime_status', w, profile_id='p')
            assert not status['connected'] and vault.calls == baseline
            result = allowed.call('provider_models', w, profile_id='p')
            assert 'secret-canary' not in json.dumps(result)
            allowed.call('runtime_connect', w, profile_id='p')
            assert not allowed.runtime_connections[w, 'p']._request_secrets
            assert not allowed.runtime_connections[w, 'p']._credentials
            allowed.call('runtime_clear', w, profile_id='p')
            changed = p.model_copy(update={'read_timeout': 31.0})
            store.execute('UPDATE llm_profiles SET config=? WHERE profile_id=?', [changed.model_dump_json(), 'p'])
            before_disconnected_request = list(vault.calls)
            with pytest.raises(AgentError):
                allowed.call('provider_models', w, profile_id='p')
            assert vault.calls == before_disconnected_request
            assert vault.values
            allowed.call('runtime_connect', w, profile_id='p')
            assert allowed.call('provider_models', w, profile_id='p')['items']
            # A hidden per-invocation override must not turn into a vault read after invalidation.
            allowed.runtime_connections[w, 'p'].register('DATAFORGE_RUNTIME_CREDENTIAL', 'override-canary')
            changed.read_timeout = 32.0
            store.execute('UPDATE llm_profiles SET config=? WHERE profile_id=?', [changed.model_dump_json(), 'p'])
            before_invalidated_request = list(vault.calls)
            with pytest.raises(AgentError):
                allowed.call('provider_models', w, profile_id='p')
            assert vault.calls == before_invalidated_request
        finally:
            allowed.close()
    assert b'secret-canary' not in (tmp_path / 'dataforge.duckdb').read_bytes()
    for path in tmp_path.rglob('*.json*'):
        assert b'secret-canary' not in path.read_bytes()


def test_bound_background_access_checks_launch_and_journals_redact(tmp_path, vault):
    from dataclasses import replace

    from dataforge.agent.contracts import AccessPolicy, AgentError
    from dataforge.agent.service import AgentService
    from dataforge.project_analysis import _BoundConnections
    from dataforge.store import Store

    with closing(Store(tmp_path)) as store:
        w, p = saved_profile(store, vault)
        service = AgentService(store, AccessPolicy(allow_write=True, allow_llm=True,
            allowed_llm_origins=(p.base_url,)))
        # Workspace/source grants remain independently required by the normal service.
        service._workspace = lambda *args, **kwargs: None
        try:
            bound = _BoundConnections(service, w, 'p', p)
            before = list(vault.calls)
            with pytest.raises(AgentError):
                bound.resolve(p.key_env)
            assert vault.calls == before
            service.policy = replace(service.policy, allowed_credential_refs=(p.key_env,))
            from dataforge.agent.contracts import QueryOptions
            service._runtime_connect(w, QueryOptions(), 'p')
            assert bound.resolve(p.key_env) == 'secret-canary'
            from dataforge.connections import current_connections
            job = service.jobs.start(w, 'credential-test', lambda progress:
                {'echo': current_connections().sanitize(current_connections().resolve(p.key_env))}, connections=bound)
            assert service.jobs.wait(job['job_id'], w, timeout=10)['result']['echo'] == '[REDACTED]'
            from dataforge.agent.contracts import QueryOptions
            service._runtime_clear(w, QueryOptions(), 'p')
            assert bound.resolve(p.key_env) == ''
        finally:
            service.close()
    for path in tmp_path.rglob('*.json*'):
        assert b'secret-canary' not in path.read_bytes()


def test_restore_and_workspace_deletion_do_not_reconnect(tmp_path, vault):
    from dataforge.cleanup import apply_cleanup, cleanup_plan
    from dataforge.database_maintenance import backup, restore_backup
    from dataforge.store import Store

    home = tmp_path / 'original'
    with closing(Store(home)) as store:
        w, p = saved_profile(store, vault)
        archive = backup(store)
        restored = restore_backup(archive, tmp_path / 'restored')
        with closing(Store(restored)) as other:
            config = json.loads(other.rows('SELECT config FROM llm_profiles')[0]['config'])
            assert config['saved_key_ref'] == ''
            assert config['key_env'] == 'DATAFORGE_SESSION_REBIND_REQUIRED'
        vault.failure = 'delete'
        plan = cleanup_plan(store, w, 'workspace')
        with pytest.raises(CredentialError):
            apply_cleanup(store, plan, 'credentials')
        assert store.workspaces() and store.rows('SELECT * FROM llm_profiles')
        vault.failure = ''
        apply_cleanup(store, plan, 'credentials')
        assert not vault.values and not store.workspaces()


def test_native_backend_ignores_discovery_and_forces_local_persistence(monkeypatch):
    import sys

    import keyring

    from dataforge.credentials import approved_backend

    monkeypatch.setattr(keyring, 'get_keyring', lambda: pytest.fail('Backend discovery is forbidden'))
    monkeypatch.setenv('PYTHON_KEYRING_BACKEND', 'keyring.backends.fail.Keyring')
    monkeypatch.setenv('KEYRING_PROPERTY_PERSIST', 'enterprise')
    if sys.platform == 'win32':
        from keyring.backends.Windows import WinVaultKeyring
        backend = approved_backend()  # Construction only; no real credential read/write.
        assert type(backend) is WinVaultKeyring and backend.persist == 2
        class Unavailable:
            def __init__(self):
                raise RuntimeError('secret-canary')
        monkeypatch.setattr('keyring.backends.Windows.WinVaultKeyring', Unavailable)
        with pytest.raises(CredentialError, match='unavailable'):
            approved_backend()
    monkeypatch.setattr(sys, 'platform', 'linux')
    with pytest.raises(CredentialError, match='not verified'):
        approved_backend()


def test_expired_override_never_reveals_saved_or_environment_key(tmp_path, vault, monkeypatch):
    for ref in ['DATAFORGE_TEST_KEY', NativeCredentials().save(tmp_path, 'w', 'p', profile(''), 'secret-canary')]:
        p = profile(ref)
        manager = RuntimeConnections().for_workspace(tmp_path, 'w').for_profile('p', p)
        monkeypatch.setenv(ref, 'environment-canary')
        manager.register(ref, 'override-canary', ttl=-1)
        assert manager.resolve(ref) == ''
        assert manager.resolve(ref) == ''
        with pytest.raises(ValueError):
            manager.scoped_environment([credential_reference(tmp_path, 'w', 'p', p, saved=True)])


def test_ui_saved_lifecycle_never_decrypts_on_render(tmp_path, vault, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from ui.common import get_store

    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    try:
        app.switch_page('ui/pages/connections.py').run()
        assert next(s for s in app.selectbox if s.label == 'Credential source').value == 'This session only'
        next(t for t in app.text_input if t.label == 'Model or deployment identifier').set_value('model')
        next(b for b in app.button if b.label == 'Save provider profile').click().run()
        next(s for s in app.selectbox if s.label == 'Provider profile').select_index(1).run()
        next(s for s in app.selectbox if s.label == 'Credential source').select('Remember on this device').run()
        field = next(t for t in app.text_input if t.label == 'Runtime credential')
        assert field.proto.type == field.proto.PASSWORD
        field.set_value('secret-canary')
        next(b for b in app.button if b.label == 'Save / replace saved key').click().run()
        assert not app.exception
        assert not next(t for t in app.text_input if t.label == 'Runtime credential').value
        assert len(vault.values) == 1
        before = list(vault.calls)
        app.run()
        assert vault.calls == before
        assert 'secret-canary' not in str(app.session_state.to_dict())
        assert 'secret-canary' not in str(app)
        next(b for b in app.button if b.label == 'Disconnect this session').click().run()
        assert vault.calls == before and vault.values
        next(t for t in app.text_input if t.label == 'Runtime credential').set_value('override-canary')
        next(b for b in app.button if b.label == 'Connect for this session').click().run()
        assert list(vault.values.values()) == ['secret-canary']
        next(s for s in app.selectbox if s.label == 'Credential source').select('This session only').run()
        next(t for t in app.text_input if t.label == 'Runtime credential').set_value('session-only-canary')
        next(b for b in app.button if b.label == 'Connect for this session').click().run()
        store = get_store(str(tmp_path))
        assert json.loads(store.rows('SELECT config FROM llm_profiles')[0]['config'])['key_env'].startswith('DATAFORGE_SESSION_')
        next(b for b in app.button if b.label == 'Disconnect this session').click().run()
        next(b for b in app.button if b.label == 'Connect saved key for this session').click().run()
        assert not app.exception
        assert next(s for s in app.selectbox if s.label == 'Credential source').value == 'Remember on this device'
        selected = json.loads(store.rows('SELECT config FROM llm_profiles')[0]['config'])
        assert selected['key_env'] == selected['saved_key_ref']
        next(t for t in app.text_input if t.label == 'Runtime credential').set_value('replacement-canary')
        next(b for b in app.button if b.label == 'Save / replace saved key').click().run()
        assert not app.exception
        assert list(vault.values.values()) == ['replacement-canary']
        import duckdb
        store = get_store(str(tmp_path))
        execute = store.execute
        def fail_profile_write(sql, params=None):
            if sql.startswith('INSERT INTO llm_profiles'):
                raise duckdb.OperationalError('secret-canary')
            return execute(sql, params)
        with monkeypatch.context() as patch:
            patch.setattr(store, 'execute', fail_profile_write)
            next(t for t in app.text_input if t.label == 'Runtime credential').set_value('failed-canary')
            next(b for b in app.button if b.label == 'Save / replace saved key').click().run()
            assert not app.exception
            assert list(vault.values.values()) == ['replacement-canary']
            assert 'secret-canary' not in str(app)
        vault.failure = 'delete'
        next(b for b in app.button if b.label == 'Delete saved key').click().run()
        assert not app.exception and vault.values
        vault.failure = ''
        next(b for b in app.button if b.label == 'Delete saved key').click().run()
        assert not app.exception and not vault.values
        assert next(s for s in app.selectbox if s.label == 'Credential source').value == 'This session only'
    finally:
        get_store(str(tmp_path)).close()
        get_store.clear(str(tmp_path))
    for path in tmp_path.rglob('*'):
        if path.is_file() and path.suffix in {'.json', '.jsonl', '.duckdb', '.wal'}:
            assert b'secret-canary' not in path.read_bytes()


def test_profile_recipient_change_and_failed_replace_preserve_saved_key(tmp_path, vault):
    from dataforge.agent.contracts import AccessPolicy, AgentError
    from dataforge.provider_service import save_profile
    from dataforge.settings_service import revision
    from dataforge.store import Store

    with closing(Store(tmp_path)) as store:
        w, p = saved_profile(store, vault)
        policy = AccessPolicy(allow_write=True, allow_config_write=True, allowed_credential_refs=(p.key_env,))
        with pytest.raises(AgentError):
            save_profile(store, policy, w, p.model_copy(update={'base_url': 'http://localhost:9999'}), revision(store, w), 'p')
        assert list(vault.values.values()) == ['secret-canary']
        vault.failure = 'delete'
        with pytest.raises(CredentialError):
            save_profile(store, policy, w, p.model_copy(update={'key_env': '', 'saved_key_ref': ''}), revision(store, w), 'p')
        assert json.loads(store.rows('SELECT config FROM llm_profiles')[0]['config'])['key_env'] == p.key_env


def test_two_new_profiles_have_distinct_session_identities(tmp_path, vault, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from ui.common import get_store

    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    try:
        app.switch_page('ui/pages/connections.py').run()
        for name in ['first', 'second']:
            next(t for t in app.text_input if t.label == 'Profile name').set_value(name)
            next(t for t in app.text_input if t.label == 'Model or deployment identifier').set_value('model')
            next(t for t in app.text_input if t.label == 'Runtime credential').set_value(name + '-session-canary')
            next(b for b in app.button if b.label == 'Connect for this session').click().run()
            next(b for b in app.button if b.label == 'Save provider profile').click().run()
            assert not app.exception and not app.error
        store = get_store(str(tmp_path))
        profiles = [Profile.model_validate_json(row['config']) for row in store.rows('SELECT config FROM llm_profiles')]
        assert len(profiles) == 2 and profiles[0].key_env != profiles[1].key_env
        assert vault.calls == []
    finally:
        get_store(str(tmp_path)).close()
        get_store.clear(str(tmp_path))


def test_mcp_grants_cannot_be_self_assigned(tmp_path, vault):
    import asyncio

    from dataforge.agent.contracts import AccessPolicy
    from dataforge.agent.mcp_server import create_server
    from dataforge.agent.service import AgentService
    from dataforge.store import Store

    with closing(Store(tmp_path)) as store:
        w, p = saved_profile(store, vault)
        service = AgentService(store, AccessPolicy(allow_write=True, allow_config_write=True, allow_llm=True,
            allowed_llm_origins=(p.base_url,)))
        try:
            server = create_server(service)
            before = list(vault.calls)
            result = asyncio.run(server.call_tool('connect_runtime_reference', {'workspace_id': w, 'profile_id': 'p'}))
            assert result.isError and vault.calls == before
            result = asyncio.run(server.call_tool('save_provider_profile', {'workspace_id': w,
                'profile_id': 'p', 'profile': p.model_dump(), 'expected_revision': service.call('providers_list', w)['settings_revision']}))
            assert result.isError and vault.calls == before
        finally:
            service.close()


def test_saved_provider_echo_is_absent_from_history_logs_exports_and_backup(tmp_path, vault):
    import logging
    import zipfile

    import httpx
    from focused_test_profiles import focused_profile

    from dataforge.configuration import export_workspace_configuration
    from dataforge.connections import connection_scope
    from dataforge.database_maintenance import backup
    from dataforge.ingestion import Importer
    from dataforge.llm import assist
    from dataforge.logging_config import JsonFormatter
    from dataforge.store import Store

    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('saved-redaction')
        Importer(store, w).files([('test.sql', b'CREATE TABLE b AS SELECT * FROM a;')], {'.sql'})
        file = store.files(w)[0]
        store.set_setting(w, 'llm_history', True)
        p = focused_profile(provider='Ollama', base_url='http://localhost:11434', model='test')
        p.key_env = p.saved_key_ref = NativeCredentials().save(tmp_path, w, 'p', p, 'secret-canary')
        # Binding capabilities again is required after changing the credential reference.
        from dataforge.model_capabilities import bind_capabilities
        p.model_capabilities = bind_capabilities(p.model_capabilities, p)
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'test', p.model_dump_json()])
        manager = RuntimeConnections().for_workspace(tmp_path, w).for_profile('p', p)
        def response(request):
            assert request.headers['Authorization'] == 'Bearer secret-canary'
            return httpx.Response(200, json={'message': {'content': '{"explanation":"secret-canary"}'}})
        with connection_scope(manager):
            result = assist(store, w, p, file['file_id'], 1, 1, profile_id='p', transport=httpx.MockTransport(response))
            assert 'secret-canary' not in json.dumps(result)
            manager.resolve(p.key_env)
            record = logging.LogRecord('dataforge.test', logging.ERROR, '', 0, 'echo secret-canary', (), None)
            assert 'secret-canary' not in JsonFormatter().format(record)
        assert 'secret-canary' not in str(store.rows('SELECT * FROM llm_records'))
        assert 'secret-canary' not in export_workspace_configuration(store, w)
        archive = backup(store)
        with zipfile.ZipFile(archive) as contents:
            assert all(b'secret-canary' not in contents.read(name) for name in contents.namelist())
    assert all(b'secret-canary' not in path.read_bytes() for path in tmp_path.rglob('*') if path.is_file())
