"""Provider setup works before saving a profile or choosing a model."""
import json
from functools import partial
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from dataforge.llm import Adapter
from ui.common import get_store


@pytest.fixture
def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    monkeypatch.setenv('DATAFORGE_OMNIROUTE_API_KEY', '')
    view = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
    view.switch_page('ui/pages/connections.py').run()
    next(s for s in view.selectbox if s.label == 'Provider').select('OmniRoute').run()
    yield view, get_store(str(tmp_path))
    get_store(str(tmp_path)).close()
    get_store.clear(str(tmp_path))


def test_unsaved_provider_setup_sets_key_tests_endpoint_and_saves_fetched_model(setup_app, monkeypatch):
    view, store = setup_app
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url)))
        assert request.headers['Authorization'] == 'Bearer test-key'
        return httpx.Response(200, json={'data': [{'id': 'auto/best-reasoning'}, {'id': 'other-model'}]})

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
    assert 'test-key' not in str(view.session_state.to_dict())


def test_endpoint_changes_drop_fetched_models_and_manual_entry_remains_available(setup_app, monkeypatch):
    view, store = setup_app
    monkeypatch.setenv('DATAFORGE_OMNIROUTE_API_KEY', 'test-key')

    def handler(request):
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


def test_unsaved_remote_connection_obeys_privacy_before_sending(setup_app, monkeypatch):
    view, _ = setup_app
    calls = []
    monkeypatch.setattr('ui.provider_settings.Adapter.models', lambda self: calls.append('sent') or ['model'])
    next(f for f in view.text_input if f.label == 'API base URL').set_value('https://example.com/v1').run()
    next(b for b in view.button if b.label == 'Test connection').click().run()
    assert not view.exception and view.error
    assert not calls


def test_fetched_model_choices_ignore_non_identifier_values(setup_app, monkeypatch):
    view, _ = setup_app
    monkeypatch.setenv('DATAFORGE_OMNIROUTE_API_KEY', 'test-key')
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'data': [{'id': {'invalid': 'value'}}, {'id': 123}, {'id': 'model'}, {'id': 'model'}]}))
    monkeypatch.setattr('ui.provider_settings.Adapter', partial(Adapter, transport=transport))
    next(b for b in view.button if b.label == 'Test connection').click().run()
    assert not view.exception and not view.error
    assert next(s for s in view.selectbox if s.label == 'Fetched models').options == ['model']
