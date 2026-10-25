"""Provider setup works before saving a profile or choosing a model."""
import json
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import pytest
from streamlit.elements.lib import policies
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
        return httpx.Response(200, json={'data': [{'id': 'auto/best-reasoning', 'context_length': 128000}, {'id': 'other-model'}]})

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


def test_endpoint_changes_drop_fetched_models_and_manual_entry_remains_available(setup_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that endpoint changes drop fetched models and manual entry remains available.

    Args:
        setup_app: Setup app value used by the test case.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    view, store = setup_app
    monkeypatch.setenv('DATAFORGE_OMNIROUTE_API_KEY', 'test-key')

    def handler(request: pytest.FixtureRequest) -> Any:
        """Handle handler for the test scenario.

        Args:
            request: Pytest fixture describing the active test request.

        Returns:
            Value produced for the test scenario.
        """
        if request.url.port == 20129:
            return httpx.Response(401, json={'error': 'test-key'})
        return httpx.Response(200, json={'data': [{'id': 'old-endpoint-model'}]})

    monkeypatch.setattr('ui.provider_settings.Adapter', partial(Adapter, transport=httpx.MockTransport(handler)))
    next(b for b in view.button if b.label == 'Test connection').click().run()
    assert any(s.label == 'Fetched models' for s in view.selectbox)
    next(f for f in view.text_input if f.label == 'API base URL').set_value('http://localhost:20129/v1').run()
    assert not any(s.label == 'Fetched models' for s in view.selectbox)
    next(b for b in view.button if b.label == 'Test connection').click().run()
    assert view.error and not view.exception
    assert 'test-key' not in str([e.value for e in view.error])
    assert not any(s.label == 'Fetched models' for s in view.selectbox)
    next(f for f in view.text_input if f.label == 'Model or deployment identifier').set_value('manual-model')
    next(b for b in view.button if b.label == 'Save provider profile').click().run()
    assert not view.exception
    config = json.loads(store.rows('SELECT config FROM llm_profiles')[0]['config'])
    assert config['model'] == 'manual-model' and config['base_url'] == 'http://localhost:20129/v1'


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


def test_fetched_model_choices_ignore_non_identifier_values(setup_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that fetched model choices ignore non identifier values.

    Args:
        setup_app: Setup app value used by the test case.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    view, _ = setup_app
    monkeypatch.setenv('DATAFORGE_OMNIROUTE_API_KEY', 'test-key')
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'data': [{'id': {'invalid': 'value'}}, {'id': 123}, {'id': 'model'}, {'id': 'model'}]}))
    monkeypatch.setattr('ui.provider_settings.Adapter', partial(Adapter, transport=transport))
    next(b for b in view.button if b.label == 'Test connection').click().run()
    assert not view.exception and not view.error
    assert next(s for s in view.selectbox if s.label == 'Fetched models').options == ['model']


def test_invalid_draft_fields_keep_connection_page_editable(setup_app):
    view, _ = setup_app
    next(f for f in view.text_input if f.label == 'API base URL').set_value('localhost:20128').run()
    assert not view.exception
    assert next(b for b in view.button if b.label == 'Inspect selected model limits').disabled
    next(f for f in view.text_input if f.label == 'API base URL').set_value('http://localhost:20128/v1').run()
    assert not view.exception


def test_saved_model_can_be_edited_and_replaced_without_state_warning(setup_app, monkeypatch, caplog):
    """Saved defaults, manual edits and fetched selections share one widget state."""
    view, store = setup_app
    next(s for s in view.selectbox if s.label == 'Provider').select('LM Studio').run()
    next(f for f in view.text_input if f.label == 'Model or deployment identifier').set_value('saved-model')
    next(b for b in view.button if b.label == 'Save provider profile').click().run()
    profile_id = store.rows('SELECT profile_id FROM llm_profiles')[0]['profile_id']
    next(s for s in view.selectbox if s.label == 'Provider profile').select(profile_id).run()
    assert next(f for f in view.text_input if f.label == 'Model or deployment identifier').value == 'saved-model'

    next(f for f in view.text_input if f.label == 'Model or deployment identifier').set_value('manual-model').run()
    view.run()
    assert next(f for f in view.text_input if f.label == 'Model or deployment identifier').value == 'manual-model'

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'data': [{'id': 'fetched-model'}]}))
    monkeypatch.setattr('ui.provider_settings.Adapter', partial(Adapter, transport=transport))
    monkeypatch.setattr(policies, '_shown_default_value_warning', False)
    monkeypatch.setattr(policies._LOGGER, 'handlers', [caplog.handler])
    next(b for b in view.button if b.label == 'Discover models').click().run()
    next(s for s in view.selectbox if s.label == 'Fetched models').select('fetched-model').run()
    assert not view.exception and not view.error
    assert next(f for f in view.text_input if f.label == 'Model or deployment identifier').value == 'fetched-model'
    next(b for b in view.button if b.label == 'Save provider profile').click().run()
    assert not view.exception and not view.error
    config = json.loads(store.rows('SELECT config FROM llm_profiles WHERE profile_id=?', [profile_id])[0]['config'])
    assert config['model'] == 'fetched-model'
    assert not any('was created with a default value' in record.getMessage() for record in caplog.records)
