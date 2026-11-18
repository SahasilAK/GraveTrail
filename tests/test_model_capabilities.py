"""Provider metadata is capacity evidence, never a spend authorization."""
import json

from dataforge.llm import Profile


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
