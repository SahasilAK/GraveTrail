"""Provider metadata is capacity evidence, never a spend authorization."""
import json

import httpx
import pytest

from dataforge.llm import Adapter, Profile


def test_catalog_preserves_names_and_normalizes_limits_without_raw_fields():
    profile = Profile(provider='OmniRoute', base_url='http://localhost:20128/v1', model='auto/best-reasoning')
    payload = {'data': [{'id': profile.model, 'context_length': 1048576, 'max_input_tokens': 1048576,
        'max_output_tokens': 512000, 'description': 'untrusted text', 'key': 'never persist'},
        {'id': profile.model, 'context_length': 64000}, {'id': {'bad': 'identifier'}}]}
    with Adapter(profile, httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as adapter:
        catalog = adapter.model_catalog()
        assert adapter.models() == [profile.model]
    assert len(catalog) == 1
    caps = catalog[0].capabilities
    assert (caps.context_tokens, caps.input_tokens, caps.output_tokens) == (64000, 1048576, 512000)
    assert caps.dynamic and caps.window == 'combined'
    assert 'never persist' not in catalog[0].model_dump_json()
    assert 'untrusted text' not in catalog[0].model_dump_json()


@pytest.mark.parametrize('bad', [True, False, 0, -1, 10.5, '100000', None, 10**20])
def test_bad_provider_numbers_remain_unknown(bad):
    from dataforge.model_capabilities import normalize_model
    result = normalize_model({'id': 'm', 'context_length': bad, 'max_output_tokens': bad}, 'OpenAI compatible')
    assert result.capabilities.context_tokens is None and result.capabilities.output_tokens is None


def test_native_and_endpoint_constraints_are_not_confused_with_aggregate_maxima():
    from dataforge.model_capabilities import normalize_model
    gemini = normalize_model({'name': 'models/gemini-test', 'inputTokenLimit': 1000000,
                             'outputTokenLimit': 65536}, 'Gemini')
    assert gemini.id == 'models/gemini-test'
    # Separate field names alone do not prove independent budgets on every model generation.
    assert gemini.capabilities.window == 'combined' and gemini.capabilities.context_tokens is None
    separate = normalize_model({'id': 'documented-separate', 'inputTokenLimit': 1000,
                                'outputTokenLimit': 100, 'window_type': 'separate'}, 'Gemini')
    assert separate.capabilities.window == 'separate'
    router = normalize_model({'id': 'vendor/model', 'context_length': 128000,
        'top_provider': {'context_length': 64000, 'max_completion_tokens': 4096},
        'max_prompt_tokens': 32000}, 'OpenRouter')
    assert router.capabilities.context_tokens == 64000
    assert router.capabilities.input_tokens == 32000
    assert router.capabilities.output_tokens == 4096


def test_selected_capabilities_bind_to_recipient_model_and_reference():
    from dataforge.model_capabilities import bind_capabilities, normalize_model
    profile = Profile(provider='OmniRoute', base_url='http://localhost:20128/v1', model='m')
    caps = bind_capabilities(normalize_model({'id': 'm', 'context_length': 64000}, profile.provider).capabilities, profile)
    saved = Profile(**(profile.model_dump() | {'model_capabilities': caps.model_dump()}))
    assert saved.model_capabilities.context_tokens == 64000
    for change in ({'model': 'other'}, {'base_url': 'http://localhost:20129/v1'},
                   {'key_env': 'DATAFORGE_OTHER_KEY'}, {'api_version': 'different'}, {'auth': 'none'}):
        changed = Profile.model_validate(saved.model_dump() | change)
        assert changed.model_capabilities is None
    # Timeout/output tuning does not change who receives the request.
    assert Profile.model_validate(saved.model_dump() | {'timeout': 50}).model_capabilities is not None
    assert Profile.model_validate_json(saved.model_dump_json()).model_capabilities == saved.model_capabilities
    assert not json.loads(profile.model_dump_json()).get('model_capabilities')


def test_explicit_selected_ollama_inspection_does_not_load_the_model():
    requests = []
    def respond(request):
        requests.append((request.method, request.url.path))
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'local-model'}]})
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'model_info': {'llama.context_length': 128000}})
        return httpx.Response(200, json={'models': [{'name': 'local-model', 'context_length': 8192}]})
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='local-model')
    with Adapter(profile, httpx.MockTransport(respond)) as adapter:
        assert adapter.models() == ['local-model']
        result = adapter.model_details('local-model')
    assert result.capabilities.context_tokens == 8192
    assert requests == [('GET', '/api/tags'), ('POST', '/api/show'), ('GET', '/api/ps')]


def test_lm_studio_inspection_falls_back_to_native_loaded_context():
    requests = []
    profile = Profile(provider='LM Studio', base_url='http://localhost:1997/v1', model='qwen/qwen3.5-9b')

    def respond(request):
        requests.append((request.method, str(request.url)))
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'data': [{'id': profile.model, 'max_output_tokens': 8192}]})
        return httpx.Response(200, json={'models': [
            {'key': 'other-model', 'max_context_length': 1024},
            {'key': profile.model, 'max_context_length': 262144,
             'loaded_instances': [{'id': profile.model, 'config': {'context_length': 38912}}]}]})

    with Adapter(profile, httpx.MockTransport(respond)) as adapter:
        result = adapter.model_details(profile.model)
    assert result.capabilities.context_tokens == 38912
    assert result.capabilities.input_tokens is None
    assert result.capabilities.output_tokens == 8192
    assert result.capabilities.source == 'runtime'
    assert result.capabilities.current_for(profile)
    assert profile.max_tokens == 2048 and profile.model_capabilities is None
    assert requests == [('GET', 'http://localhost:1997/v1/models'),
                        ('GET', 'http://localhost:1997/api/v1/models')]


def test_lm_studio_inspection_keeps_catalog_context_without_native_request():
    requests = []
    profile = Profile(provider='LM Studio', base_url='http://localhost:1997/v1', model='m')

    def respond(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={'data': [{'id': 'm', 'context_length': 32000}]})

    with Adapter(profile, httpx.MockTransport(respond)) as adapter:
        result = adapter.model_details('m')
    assert result.capabilities.context_tokens == 32000
    assert requests == ['/v1/models']


@pytest.mark.parametrize('native', [None, {}, {'models': None}, {'models': 'bad'},
    {'models': [{'key': 'other-model', 'max_context_length': 8192}]},
    {'models': [{'key': 'm', 'max_context_length': True,
                 'loaded_instances': [{'config': {'context_length': '38912'}}]}]}])
def test_lm_studio_missing_native_metadata_preserves_unknown_limits_and_defaults(native):
    requests = []
    profile = Profile(provider='LM Studio', base_url='http://localhost:1997/v1', model='m')

    def respond(request):
        requests.append(request.url.path)
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'data': [{'id': 'm'}]})
        return httpx.Response(404) if native is None else httpx.Response(200, json=native)

    with Adapter(profile, httpx.MockTransport(respond)) as adapter:
        result = adapter.model_details('m')
    assert result.capabilities.context_tokens is None
    assert result.capabilities.input_tokens is None and result.capabilities.output_tokens is None
    assert profile.max_tokens == 2048 and profile.context_chars == 16000
    assert requests == ['/v1/models', '/api/v1/models']


def test_lm_studio_native_fallback_can_find_model_missing_from_catalog():
    profile = Profile(provider='LM Studio', base_url='http://localhost:1997/v1', model='m')

    def respond(request):
        if request.url.path == '/v1/models':
            return httpx.Response(200, json={'data': []})
        return httpx.Response(200, json={'models': [{'key': 'm', 'max_context_length': 262144}]})

    with Adapter(profile, httpx.MockTransport(respond)) as adapter:
        result = adapter.model_details('m')
    assert result.capabilities.context_tokens == 262144
    assert result.capabilities.source == 'native'


@pytest.mark.parametrize(('instances', 'expected', 'source'), [
    ([{'config': {'context_length': 38912}}, {'config': {'context_length': 8192}}], 8192, 'runtime'),
    ([{'config': {'context_length': 300000}}], 262144, 'runtime'),
    ([None, {'config': None}, {'config': {'context_length': False}}], 262144, 'native'),
    (None, 262144, 'native'),
])
def test_lm_studio_native_context_respects_loaded_and_model_constraints(instances, expected, source):
    from dataforge.model_capabilities import normalize_model
    result = normalize_model({'key': 'm', 'max_context_length': 262144, 'loaded_instances': instances}, 'LM Studio')
    assert result.capabilities.context_tokens == expected
    assert result.capabilities.source == source


def test_other_providers_do_not_probe_lm_studio_native_endpoint():
    requests = []
    profile = Profile(provider='OpenAI compatible', base_url='http://localhost:1997/v1', model='m')

    def respond(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={'data': [{'id': 'm'}]})

    with Adapter(profile, httpx.MockTransport(respond)) as adapter:
        result = adapter.model_details('m')
    assert result.capabilities.context_tokens is None
    assert requests == ['/v1/models']


def test_metadata_refresh_preserves_runtime_binding_and_execution_revision(tmp_path):
    from dataforge.agent.service import AgentService
    from dataforge.connections import RuntimeConnections
    from dataforge.llm import Profile
    from dataforge.model_capabilities import ModelCapabilities, bind_capabilities, runtime_profile
    from dataforge.settings_service import revision
    from dataforge.store import Store
    store = Store(tmp_path)
    w = store.create_workspace('metadata identity')
    p = Profile(provider='OmniRoute', base_url='http://localhost:20128/v1', model='m')
    p.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=128000), p)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', p.model_dump_json()])
    service = AgentService(store)
    manager = RuntimeConnections()
    service.runtime_connections[w, 'p'] = manager
    service.runtime_profiles[w, 'p'] = runtime_profile(p)
    before = revision(store, w)
    refreshed = p.model_copy(update={'model_capabilities': p.model_capabilities.model_copy(
        update={'observed_at': p.model_capabilities.observed_at + 1, 'source': 'native'})})
    store.execute('UPDATE llm_profiles SET config=? WHERE profile_id=?', [refreshed.model_dump_json(), 'p'])
    assert revision(store, w) == before
    assert service._runtime_manager(w, 'p', refreshed) is manager
    refreshed.model_capabilities = refreshed.model_capabilities.model_copy(update={'context_tokens': 64000})
    store.execute('UPDATE llm_profiles SET config=? WHERE profile_id=?', [refreshed.model_dump_json(), 'p'])
    assert revision(store, w) != before
    service.close()
    store.close()
