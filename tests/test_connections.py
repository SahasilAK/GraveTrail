import os

import httpx
import pytest

from dataforge.connections import RuntimeConnections, connection_scope
from dataforge.llm import Adapter, Profile


def test_session_keys_are_isolated_and_environment_is_read_only(monkeypatch):
    monkeypatch.setenv('DATAFORGE_OPENAI_API_KEY', 'launch-dummy')
    before = dict(os.environ)
    first, second = RuntimeConnections(), RuntimeConnections()
    profile = Profile(provider='OpenAI', base_url='https://api.openai.com/v1', model='test',
                      key_env='DATAFORGE_OPENAI_API_KEY')
    first.register(profile.key_env, 'session-dummy')
    with connection_scope(first), Adapter(profile) as adapter:
        assert adapter._headers()['Authorization'] == 'Bearer session-dummy'
    with connection_scope(second), Adapter(profile) as adapter:
        assert adapter._headers()['Authorization'] == 'Bearer launch-dummy'
    first.clear()
    assert first.resolve(profile.key_env) == 'launch-dummy'
    assert dict(os.environ) == before
    assert 'session-dummy' not in repr(first)


def test_expiration_scoped_environment_and_redaction(monkeypatch):
    manager = RuntimeConnections()
    manager.register('DATAFORGE_CUSTOM_API_KEY', 'dummy-sensitive-123')
    assert manager.redact('echo dummy-sensitive-123 Authorization: Bearer abc') == 'echo [REDACTED] Authorization: Bearer [REDACTED]'
    assert manager.scoped_environment(['DATAFORGE_CUSTOM_API_KEY']) == {'DATAFORGE_CUSTOM_API_KEY': 'dummy-sensitive-123'}
    with pytest.raises(ValueError):
        manager.register('OPENAI_API_KEY', 'bad')
    manager.register('DATAFORGE_CUSTOM_API_KEY', 'expired', ttl=0)
    assert manager.resolve('DATAFORGE_CUSTOM_API_KEY') == ''


def test_provider_echo_is_redacted_before_persistence(tmp_path):
    from dataforge.ingestion import Importer
    from dataforge.llm import assist
    from dataforge.store import Store

    store = Store(tmp_path)
    workspace = store.create_workspace('test')
    Importer(store, workspace).files([('test.sql', b'CREATE TABLE b AS SELECT * FROM a;')], {'.sql'})
    file = store.files(workspace)[0]
    store.set_setting(workspace, 'llm_history', True)
    manager = RuntimeConnections()
    manager.register('DATAFORGE_TEST_API_KEY', 'dummy-sensitive-123')
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='test', key_env='DATAFORGE_TEST_API_KEY')
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={'message': {'content': '{"explanation":"dummy-sensitive-123"}'}}))
    with connection_scope(manager):
        result = assist(store, workspace, profile, file['file_id'], 1, 1, transport=transport)
    assert 'dummy-sensitive-123' not in str(result)
    assert 'dummy-sensitive-123' not in str(store.rows('SELECT * FROM llm_records'))
    store.close()
    assert all(b'dummy-sensitive-123' not in p.read_bytes() for p in tmp_path.rglob('*') if p.is_file())


def test_masked_ui_credential_is_cleared_without_persistence(tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    app.switch_page('ui/pages/settings.py').run()
    app.segmented_control[0].set_value('LLM providers').run()
    next(t for t in app.text_input if t.label == 'Credential environment variable name').set_value('DATAFORGE_OLLAMA_API_KEY')
    next(t for t in app.text_input if t.label == 'Model or deployment identifier').set_value('test')
    next(b for b in app.button if b.label == 'Save provider profile').click().run()
    profile = next(s for s in app.selectbox if s.label == 'Provider profile')
    profile.select_index(1).run()
    next(t for t in app.text_input if t.label == 'Runtime credential').set_value('ui-dummy-secret')
    next(b for b in app.button if b.label == 'Connect for this session').click().run()
    assert not app.exception
    assert app.session_state['runtime_connections'].resolve('DATAFORGE_OLLAMA_API_KEY') == 'ui-dummy-secret'
    assert not next(t for t in app.text_input if t.label == 'Runtime credential').value
    next(b for b in app.button if b.label == 'Clear runtime credentials').click().run()
    assert not app.exception
    assert app.session_state['runtime_connections'].resolve('DATAFORGE_OLLAMA_API_KEY') == ''


def test_json_escaped_secret_is_redacted_before_persistence(tmp_path):
    import json

    from dataforge.ingestion import Importer
    from dataforge.llm import assist
    from dataforge.store import Store

    store = Store(tmp_path)
    w = store.create_workspace('test')
    Importer(store, w).files([('q.sql', b'SELECT 1;')], {'.sql'})
    store.set_setting(w, 'llm_history', True)
    manager = RuntimeConnections()
    secret = 'dummy"quoted\\secret'
    manager.register('DATAFORGE_TEST_API_KEY', secret)
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='test', key_env='DATAFORGE_TEST_API_KEY')
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={'message': {'content': json.dumps({'explanation': secret})}}))
    with connection_scope(manager):
        result = assist(store, w, profile, store.files(w)[0]['file_id'], 1, 1, transport=transport)
    assert result['result']['explanation'] != secret
    details = json.loads(store.rows('SELECT details FROM llm_records')[0]['details'])
    assert details['result']['explanation'] != secret
    assert secret not in details['response'] and json.dumps(secret)[1:-1] not in details['response']
    store.close()


def test_explicit_environment_reference_redacts_arbitrary_variable_names(monkeypatch):
    monkeypatch.setenv('DATAFORGE_AUTH_CREDENTIAL', 'dummy-environment-sensitive-123')
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='test', key_env='DATAFORGE_AUTH_CREDENTIAL')
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={'message': {'content': '{"explanation":"dummy-environment-sensitive-123"}'}}))
    with Adapter(profile, transport=transport) as adapter:
        content, _ = adapter.complete('test', 'test')
    assert 'dummy-environment-sensitive-123' not in content


def test_sanitize_redacts_keys_values_and_shared_containers_without_mutation():
    manager = RuntimeConnections()
    secret = 'dummy"quoted\\secret'
    manager.register('DATAFORGE_TEST_API_KEY', secret)
    shared = {secret: [secret, None, True, 42, 1.5]}
    original = {'first': shared, 'second': shared}

    result = manager.sanitize(original)

    expected = {'[REDACTED]': ['[REDACTED]', None, True, 42, 1.5]}
    assert result == {'first': expected, 'second': expected}
    assert original['first'] is shared and original['second'] is shared
    assert shared[secret][0] == secret
    assert manager.sanitize(secret) == '[REDACTED]'
    assert manager.sanitize(None) is None


@pytest.mark.parametrize('kind', ['dict', 'list', 'mixed'])
@pytest.mark.parametrize('depth', [65, 1100])
def test_sanitize_rejects_excessive_nesting(kind, depth):
    value = 'dummy-sensitive-123'
    for level in range(depth):
        value = {'child': value} if kind == 'dict' or (kind == 'mixed' and level % 2) else [value]

    with pytest.raises(ValueError, match='nesting'):
        RuntimeConnections().sanitize(value)


def test_sanitize_redacts_at_nesting_limit():
    manager = RuntimeConnections()
    manager.register('DATAFORGE_TEST_API_KEY', 'dummy-sensitive-123')
    value = 'dummy-sensitive-123'
    for _ in range(64):
        value = [value]

    result = manager.sanitize(value)
    for _ in range(64):
        result = result[0]
    assert result == '[REDACTED]'


@pytest.mark.parametrize('kind', ['dict', 'list', 'mixed'])
def test_sanitize_rejects_cycles(kind):
    if kind == 'dict':
        value = {}
        value['self'] = value
    elif kind == 'list':
        value = []
        value.append(value)
    else:
        value = {'child': []}
        value['child'].append(value)

    manager = RuntimeConnections()
    with pytest.raises(ValueError, match='cyclic'):
        manager.sanitize(value)
    assert manager.sanitize({'safe': ['value']}) == {'safe': ['value']}
