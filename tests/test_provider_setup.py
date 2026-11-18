"""Provider setup works before saving a profile or choosing a model."""
import json
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from dataforge.llm import Adapter
from ui.common import get_store


@pytest.fixture
def setup_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Handle setup app for the test scenario.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    monkeypatch.setenv('DATAFORGE_OMNIROUTE_API_KEY', '')
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/connections.py').run()
    next(s for s in view.selectbox if s.label == 'Provider').select('OmniRoute').run()
    yield view, get_store(str(tmp_path))
    get_store(str(tmp_path)).close()
    get_store.clear(str(tmp_path))


def test_unsaved_provider_setup_sets_key_tests_endpoint_and_saves_fetched_model(setup_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that unsaved provider setup sets key tests endpoint and saves fetched model.

    Args:
        setup_app: Setup app value used by the test case.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    view, store = setup_app
    calls = []

    def handler(request: pytest.FixtureRequest) -> Any:
        """Handle handler for the test scenario.

        Args:
            request: Pytest fixture describing the active test request.

        Returns:
            Value produced for the test scenario.
        """
        calls.append((request.method, str(request.url)))
        assert request.headers['Authorization'] == 'Bearer test-key'
        return httpx.Response(200, json={'data': [
            {'id': 'auto/best-reasoning', 'context_length': 128000}, {'id': 'other-model'},
            {'id': 'other-model'}, {'id': 123}, {'id': {'invalid': 'value'}},
        ]})

    monkeypatch.setattr('ui.provider_settings.Adapter', partial(Adapter, transport=httpx.MockTransport(handler)))
    fields = [getattr(node, 'label', '') for node in view.main]
    assert fields.index('API base URL') < fields.index('Environment credential value (optional)')
    assert fields.index('Environment credential value (optional)') < fields.index('Test connection')
    assert fields.index('Test connection') < fields.index('Model or deployment identifier')
    assert not store.rows('SELECT * FROM llm_profiles') and not calls

    next(f for f in view.text_input if f.label == 'Environment credential value (optional)').set_value('test-key')
    next(b for b in view.button if b.label == 'Set environment variable').click().run()
    next(b for b in view.button if b.label == 'Test connection').click().run()
    assert not view.exception and not view.error
    assert calls == [('GET', 'http://localhost:20128/v1/models')]
    fetched = next(s for s in view.selectbox if s.label == 'Fetched models')
    assert fetched.options == ['auto/best-reasoning', 'other-model']
    fetched.select('auto/best-reasoning').run()
    assert next(f for f in view.text_input if f.label == 'Model or deployment identifier').value == 'auto/best-reasoning'
    assert not store.rows('SELECT * FROM llm_profiles')
    next(b for b in view.button if b.label == 'Save provider profile').click().run()
    assert not view.exception
    config = json.loads(store.rows('SELECT config FROM llm_profiles')[0]['config'])
    assert config['model'] == 'auto/best-reasoning'
    assert config['key_env'] == 'DATAFORGE_OMNIROUTE_API_KEY'
    assert config['read_timeout'] == 300 and config['connect_timeout'] == 5
    assert config['unknown_retries'] == config['retries'] == 2
    assert config['model_capabilities']['context_tokens'] == 128000
    assert config['model_capabilities']['dynamic'] is True
    assert 'test-key' not in str(view.session_state.to_dict())


def test_unsaved_remote_connection_obeys_privacy_before_sending(setup_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that unsaved remote connection obeys privacy before sending.

    Args:
        setup_app: Setup app value used by the test case.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    view, _ = setup_app
    calls = []
    monkeypatch.setattr('ui.provider_settings.Adapter.models', lambda self: calls.append('sent') or ['model'])
    next(f for f in view.text_input if f.label == 'API base URL').set_value('https://example.com/v1').run()
    next(b for b in view.button if b.label == 'Test connection').click().run()
    assert not view.exception and view.error
    assert not calls
