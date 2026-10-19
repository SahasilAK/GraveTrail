"""Profile/routing operations with launch-bound references and recipient origins."""
import time
import uuid
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from dataforge.agent.contracts import AgentError
from dataforge.configuration import LLMResourceSettings
from dataforge.connections import RuntimeConnections, connection_scope
from dataforge.llm import ROUTABLE_TASKS as TASKS
from dataforge.llm import Adapter, Profile, ProviderError, is_local, response_object
from dataforge.llm_resources import request_slot
from dataforge.settings_service import check_revision, revision

READS = {'providers_list', 'provider_get', 'routing_get', 'runtime_status'}
WRITES = {'provider_save', 'provider_remove', 'routing_update', 'runtime_connect', 'runtime_clear',
          'provider_models', 'provider_test'}


def origin(url):
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    return parsed.scheme.lower(), (parsed.hostname or '').lower(), port


class Routing(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    default_profile: str = ''
    task_models: dict[str, str] = Field(default_factory=dict)
    fallback_profiles: list[str] = Field(default_factory=list, max_length=20)


def get_profile(store, workspace, profile_id):
    rows = store.rows('SELECT config FROM llm_profiles WHERE workspace_id=? AND profile_id=?', [workspace, profile_id])
    if not rows:
        raise AgentError('not_found', 'Provider profile does not exist in this workspace')
    return Profile.model_validate_json(rows[0]['config'])


def save_profile(store, policy, workspace, profile, expected_revision, profile_id=''):
    policy.require('config')
    check_revision(store, workspace, expected_revision)
    profile = Profile.model_validate(profile, strict=True)
    if profile.key_env and profile.key_env not in policy.allowed_credential_refs:
        raise AgentError('credential_unavailable', 'Approve this named credential reference at launch before saving')
    if profile_id:
        get_profile(store, workspace, profile_id)
    else:
        profile_id = uuid.uuid4().hex
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?) ON CONFLICT(profile_id) DO UPDATE SET name=excluded.name,config=excluded.config',
                  [profile_id, workspace, profile.name, profile.model_dump_json()])
    return {'profile_id': profile_id, 'settings_revision': revision(store, workspace)}


def save_routing(store, policy, workspace, values, expected_revision):
    policy.require('config')
    check_revision(store, workspace, expected_revision)
    routing = Routing.model_validate(values)
    if set(routing.task_models) - set(TASKS):
        raise AgentError('validation_failed', 'Routing supports documented manual and project AI tasks')
    ids = {p['profile_id'] for p in store.rows('SELECT profile_id FROM llm_profiles WHERE workspace_id=?', [workspace])}
    refs = {routing.default_profile, *routing.task_models.values(), *routing.fallback_profiles} - {''}
    if refs - ids or len(routing.fallback_profiles) != len(set(routing.fallback_profiles)):
        raise AgentError('validation_failed', 'Routing references must be existing, unique workspace profiles')
    with store.transaction():
        for key, value in routing.model_dump().items():
            store.set_setting(workspace, key, value)
    return {'settings_revision': revision(store, workspace), 'routing': routing.model_dump()}


def authorize_provider(store, policy, workspace, profile):
    policy.require('network')
    if origin(profile.base_url) not in {origin(url) for url in policy.allowed_llm_origins}:
        raise AgentError('network_not_allowed', 'Provider origin is not explicitly allowed for this launch')
    if profile.key_env and profile.key_env not in policy.allowed_credential_refs:
        raise AgentError('credential_unavailable', 'Named credential reference is not approved for this launch')
    if not is_local(profile.base_url) and not store.setting(workspace, 'external_llm', False):
        raise AgentError('network_not_allowed', 'Workspace external requests are disabled')


class ProviderOperations:
    def _runtime_manager(self, w, profile_id, profile):
        key = (w, profile_id)
        manager = self.runtime_connections.get(key)
        if manager is not None and self.runtime_profiles.get(key) != profile.model_dump_json():
            manager.clear()
            self.runtime_connections.pop(key, None)
            self.runtime_profiles.pop(key, None)
            return None
        return manager

    def _public_profile(self, profile):
        data = profile.model_dump()
        if data['key_env'] not in self.policy.allowed_credential_refs:
            data['key_env'] = ''
        return data

    def _providers_list(self, w, opts):
        rows = self.store.rows('SELECT profile_id,config FROM llm_profiles WHERE workspace_id=? ORDER BY name,profile_id', [w])
        return self._page(w, opts, 'providers', [{'profile_id': r['profile_id'],
            'profile': self._public_profile(Profile.model_validate_json(r['config']))} for r in rows],
            settings_revision=revision(self.store, w))

    def _provider_get(self, w, opts, profile_id):
        return {'profile_id': profile_id, 'profile': self._public_profile(get_profile(self.store, w, profile_id)),
                'settings_revision': revision(self.store, w)}

    def _provider_save(self, w, opts, profile, expected_revision, profile_id=''):
        return save_profile(self.store, self.policy, w, profile, expected_revision, profile_id)

    def _provider_remove(self, w, opts, profile_id, expected_revision):
        self.policy.require('config')
        check_revision(self.store, w, expected_revision)
        get_profile(self.store, w, profile_id)
        route = self._routing_get(w, opts)['routing']
        if profile_id in {route['default_profile'], *route['task_models'].values(), *route['fallback_profiles']}:
            raise AgentError('conflict', 'Remove routing references before removing this profile')
        self.store.execute('DELETE FROM llm_profiles WHERE workspace_id=? AND profile_id=?', [w, profile_id])
        manager = self.runtime_connections.pop((w, profile_id), None)
        self.runtime_profiles.pop((w, profile_id), None)
        if manager:
            manager.clear()
        return {'removed': profile_id, 'settings_revision': revision(self.store, w)}

    def _routing_get(self, w, opts):
        return {'routing': {key: self.store.setting(w, key, value) for key, value in Routing().model_dump().items()},
                'tasks': TASKS, 'settings_revision': revision(self.store, w)}

    def _routing_update(self, w, opts, values, expected_revision):
        return save_routing(self.store, self.policy, w, values, expected_revision)

    def _runtime_status(self, w, opts, profile_id):
        profile = get_profile(self.store, w, profile_id)
        manager = self._runtime_manager(w, profile_id, profile)
        approved = not profile.key_env or profile.key_env in self.policy.allowed_credential_refs
        return {'profile_id': profile_id, 'reference': profile.key_env if approved else '',
                'approved': approved, 'connected': manager is not None,
                'restart': 'Bindings last only for this owning process; UI sessions are separate'}

    def _runtime_connect(self, w, opts, profile_id):
        profile = get_profile(self.store, w, profile_id)
        authorize_provider(self.store, self.policy, w, profile)
        manager = RuntimeConnections()
        secret = manager.resolve(profile.key_env)
        if profile.key_env and not secret:
            manager.clear()
            raise AgentError('credential_unavailable', 'Approved launch reference is unavailable')
        # Internal alias supports legacy launch names without mutating environment or saved profiles.
        if secret:
            manager.register('DATAFORGE_RUNTIME_CREDENTIAL', secret)
        self.runtime_connections[(w, profile_id)] = manager
        self.runtime_profiles[(w, profile_id)] = profile.model_dump_json()
        return self._runtime_status(w, opts, profile_id)

    def _runtime_clear(self, w, opts, profile_id):
        get_profile(self.store, w, profile_id)
        manager = self.runtime_connections.pop((w, profile_id), None)
        self.runtime_profiles.pop((w, profile_id), None)
        if manager:
            manager.clear()
        return self._runtime_status(w, opts, profile_id)

    def _provider_operation(self, w, opts, profile_id, operation):
        profile = get_profile(self.store, w, profile_id)
        authorize_provider(self.store, self.policy, w, profile)
        manager = self._runtime_manager(w, profile_id, profile) or RuntimeConnections()
        if manager.registered('DATAFORGE_RUNTIME_CREDENTIAL'):
            profile = profile.model_copy(update={'key_env': 'DATAFORGE_RUNTIME_CREDENTIAL'})
        if profile.key_env and not manager.resolve(profile.key_env):
            raise AgentError('credential_unavailable', 'Approved credential is unavailable; use a launch reference or hidden local prompt')
        resources = LLMResourceSettings.model_validate({k: self.store.setting(w, k, v) for k, v in LLMResourceSettings().model_dump().items()})
        started = time.perf_counter()
        try:
            with connection_scope(manager), request_slot(self.store.home, w, resources.llm_concurrency), Adapter(profile, self.provider_transport) as adapter:
                if operation == 'models':
                    models = adapter.models()
                    result = self._page(w, opts, ['models', profile_id], models)
                else:
                    response, usage = adapter.complete('Return a JSON object with key "status".', 'Return {"status":"connected"}.')
                    if response_object(response).get('status') != 'connected':
                        raise ValueError('Connection-test contract not satisfied')
                    result = {'connected': True, 'usage': usage}
                return manager.sanitize({**result, 'duration': round(time.perf_counter() - started, 3)})
        except (ValueError, ProviderError) as exc:
            if isinstance(exc, ValueError) and ('requests are busy' in str(exc) or 'maintenance is active' in str(exc)):
                raise AgentError('busy', 'Provider request capacity is occupied; retry after the active operation finishes') from None
            raise AgentError('provider_failed', 'Provider operation failed; check approved endpoint, credential, privacy and response contract') from None
        finally:
            if (w, profile_id) not in self.runtime_connections:
                manager.clear()

    def _provider_models(self, w, opts, profile_id):
        return self._provider_operation(w, opts, profile_id, 'models')

    def _provider_test(self, w, opts, profile_id):
        return self._provider_operation(w, opts, profile_id, 'test')
