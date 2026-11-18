import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from focused_test_profiles import focused_profile

from dataforge.connections import RuntimeConnections, connection_scope
from dataforge.llm import Adapter, Profile


def test_session_keys_are_isolated_and_environment_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that session keys are isolated and environment is read only.

    Args:
        monkeypatch: Pytest fixture for isolating environment and attribute changes."""
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


@pytest.mark.parametrize('credential_mode', ['session', 'rotated_environment'])
def test_provider_echo_is_redacted_before_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, credential_mode: str) -> None:
    """Verify that provider echo is redacted before persistence.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
        credential_mode: Credential mode value used by the test case."""
    from dataforge.connections import set_credential_environment
    from dataforge.ingestion import Importer
    from dataforge.llm import assist
    from dataforge.store import Store

    store = Store(tmp_path)
    workspace = store.create_workspace('test')
    Importer(store, workspace).files([('test.sql', b'CREATE TABLE b AS SELECT * FROM a;')], {'.sql'})
    file = store.files(workspace)[0]
    store.set_setting(workspace, 'llm_history', True)
    manager = RuntimeConnections()
    if credential_mode == 'session':
        manager.register('DATAFORGE_TEST_API_KEY', 'dummy-sensitive-123')
    else:
        monkeypatch.setenv('DATAFORGE_TEST_API_KEY', '')
        set_credential_environment('DATAFORGE_TEST_API_KEY', 'dummy-sensitive-123')
    profile = focused_profile(provider='Ollama', base_url='http://localhost:11434', model='test', key_env='DATAFORGE_TEST_API_KEY')
    def handler(request: pytest.FixtureRequest) -> Any:
        """Handle handler for the test scenario.

        Args:
            request: Pytest fixture describing the active test request.

        Returns:
            Value produced for the test scenario."""
        if credential_mode == 'rotated_environment':
            set_credential_environment('DATAFORGE_TEST_API_KEY', 'replacement-dummy')
        return httpx.Response(200, json={'message': {'content': '{"explanation":"dummy-sensitive-123"}'}})

    transport = httpx.MockTransport(handler)
    with connection_scope(manager):
        result = assist(store, workspace, profile, file['file_id'], 1, 1, transport=transport)
    assert 'dummy-sensitive-123' not in str(result)
    assert 'dummy-sensitive-123' not in str(store.rows('SELECT * FROM llm_records'))
    store.close()
    assert all(b'dummy-sensitive-123' not in p.read_bytes() for p in tmp_path.rglob('*') if p.is_file())


def test_masked_ui_sets_actual_environment_without_persisting_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Verify that masked ui sets actual environment without persisting secret.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
        caplog: Pytest fixture for capturing log records."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    monkeypatch.setenv('DATAFORGE_OMNIROUTE_API_KEY', '')
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    app.switch_page('ui/pages/connections.py').run()
    next(s for s in app.selectbox if s.label == 'Provider').select('OmniRoute').run()
    next(t for t in app.text_input if t.label == 'Model or deployment identifier').set_value('test')
    next(b for b in app.button if b.label == 'Save provider profile').click().run()
    next(s for s in app.selectbox if s.label == 'Provider profile').select_index(1).run()
    field = next(t for t in app.text_input if t.label == 'Environment credential value (optional)')
    assert field.proto.type == field.proto.PASSWORD
    field.set_value('dummy-sensitive-123')
    next(b for b in app.button if b.label == 'Set environment variable').click().run()
    assert not app.exception
    assert os.environ['DATAFORGE_OMNIROUTE_API_KEY'] == 'dummy-sensitive-123'
    assert not next(t for t in app.text_input if t.label == field.label).value
    state = app.session_state.to_dict()
    assert 'dummy-sensitive-123' not in str(state)
    assert 'dummy-sensitive-123' not in str(vars(state['runtime_connections']))
    assert 'dummy-sensitive-123' not in caplog.text
    # Invalid submissions clear the field and preserve the working environment value.
    next(t for t in app.text_input if t.label == field.label).set_value('dummy\0secret')
    next(b for b in app.button if b.label == 'Set environment variable').click().run()
    assert not app.exception
    assert app.warning
    assert os.environ['DATAFORGE_OMNIROUTE_API_KEY'] == 'dummy-sensitive-123'
    assert not next(t for t in app.text_input if t.label == field.label).value
    assert 'dummy\\x00secret' not in str(app.session_state.to_dict())
    assert 'dummy\0secret' not in caplog.text

    from ui.common import get_store

    get_store(str(tmp_path)).close()
    assert all(b'dummy-sensitive-123' not in p.read_bytes() for p in tmp_path.rglob('*') if p.is_file())


def test_sanitize_redacts_keys_values_and_shared_containers_without_mutation() -> None:
    """Verify that sanitize redacts keys values and shared containers without mutation."""
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
