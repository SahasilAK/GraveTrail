"""Profile/routing operations with launch-bound references and recipient origins."""
import json
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from dataforge.agent.contracts import AccessPolicy, AgentError, QueryOptions
from dataforge.configuration import LLMResourceSettings
from dataforge.connections import RuntimeConnections, connection_scope
from dataforge.credentials import CredentialError, NativeCredentials, credential_source, owns_reference
from dataforge.llm import ROUTABLE_TASKS as TASKS
from dataforge.llm import Adapter, Profile, ProviderError, is_local, response_object
from dataforge.llm_resources import request_slot
from dataforge.model_capabilities import bind_capabilities, runtime_profile
from dataforge.settings_service import check_revision, revision
from dataforge.store import Store

READS = {'providers_list', 'provider_get', 'routing_get', 'runtime_status'}
WRITES = {'provider_save', 'provider_remove', 'routing_update', 'runtime_connect', 'runtime_clear',
          'provider_models', 'provider_test'}


def origin(url: str) -> tuple[str, str, int]:
    """Normalize a provider URL to its scheme, host, and effective port.

    Args:
        url: Provider URL to normalize.

    Returns:
        Lowercase scheme and host with the explicit or default HTTP port.
    """
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    return parsed.scheme.lower(), (parsed.hostname or '').lower(), port


class Routing(BaseModel):
    """Validate the workspace default, per-task, and fallback profiles."""
    model_config = ConfigDict(extra='forbid', strict=True)
    default_profile: str = ''
    task_models: dict[str, str] = Field(default_factory=dict)
    fallback_profiles: list[str] = Field(default_factory=list, max_length=20)


def get_profile(store: Store, workspace: str, profile_id: str) -> Profile:
    """Load and validate one provider profile belonging to a workspace.

    Args:
        store: Workspace store containing the profile.
        workspace: Workspace identifier that owns the profile.
        profile_id: Provider profile identifier.

    Returns:
        The validated provider profile.

    Raises:
        AgentError: If the profile does not exist in the workspace.
    """
    rows = store.rows('SELECT config FROM llm_profiles WHERE workspace_id=? AND profile_id=?', [workspace, profile_id])
    if not rows:
        raise AgentError('not_found', 'Provider profile does not exist in this workspace')
    return Profile.model_validate_json(rows[0]['config'])


def save_profile(store: Store, policy: AccessPolicy, workspace: str,
                 profile: Profile | dict[str, Any], expected_revision: str,
                 profile_id: str = '', *, new_profile_id: str = '') -> dict[str, Any]:
    """Validate and persist a provider profile after permission and revision checks.

    Args:
        store: Workspace store receiving the profile.
        policy: Launch policy authorizing configuration changes and credentials.
        workspace: Workspace identifier receiving the profile.
        profile: Profile model or mapping to validate.
        expected_revision: Current settings revision required for the update.
        profile_id: Existing profile identifier, or an empty value to create one.

    Returns:
        The profile identifier and resulting settings revision.
    """
    policy.require('config')
    check_revision(store, workspace, expected_revision)
    if not profile_id:
        values = profile.model_dump(exclude_unset=True) if isinstance(profile, Profile) else dict(profile)
        if values.get('provider') == 'OmniRoute':
            defaults = {'unknown_retries': 2, 'retries': 2}
            if 'timeout' not in values and 'read_timeout' not in values:
                defaults['read_timeout'] = 300
            profile = {**defaults, **values}
    profile = Profile.model_validate(profile, strict=True)
    if profile.key_env and profile.key_env not in policy.allowed_credential_refs:
        raise AgentError('credential_unavailable', 'Approve this named credential reference at launch before saving')
    if profile.saved_key_ref and profile.saved_key_ref not in policy.allowed_credential_refs:
        raise AgentError('credential_unavailable', 'Approve this saved credential reference at launch before binding')
    if profile_id:
        previous = get_profile(store, workspace, profile_id)
    else:
        profile_id = new_profile_id or uuid.uuid4().hex
        if store.rows('SELECT profile_id FROM llm_profiles WHERE profile_id=?', [profile_id]):
            raise AgentError('conflict', 'New profile identity is already in use')
        previous = None
    if credential_source(profile.key_env) == 'saved' and not owns_reference(store.home, workspace, profile_id, profile):
        raise AgentError('credential_unavailable', 'Saved credential identity changed; explicitly rebind or save a new key')
    saved_ref = profile.saved_key_ref or (profile.key_env if credential_source(profile.key_env) == 'saved' else '')
    if saved_ref and not owns_reference(store.home, workspace, profile_id, profile.model_copy(update={'key_env': saved_ref})):
        raise AgentError('credential_unavailable', 'Delete the saved key before changing its recipient, or explicitly rebind after restore')
    old_ref = (previous.saved_key_ref or (previous.key_env if credential_source(previous.key_env) == 'saved' else '')) if previous else ''
    if old_ref and old_ref != saved_ref:
        if old_ref not in policy.allowed_credential_refs:
            raise AgentError('credential_unavailable', 'Approve the previous saved reference before replacing it')
    with store.transaction():
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?) ON CONFLICT(profile_id) DO UPDATE SET name=excluded.name,config=excluded.config',
                      [profile_id, workspace, profile.name, profile.model_dump_json()])
        if old_ref and old_ref != saved_ref:
            NativeCredentials().delete(store.home, workspace, profile_id, previous)
    return {'profile_id': profile_id, 'settings_revision': revision(store, workspace)}


def save_routing(store: Store, policy: AccessPolicy, workspace: str,
                 values: Routing | dict[str, Any], expected_revision: str) -> dict[str, Any]:
    """Validate and persist workspace provider routing.

    Args:
        store: Workspace store receiving the routing settings.
        policy: Launch policy authorizing configuration changes.
        workspace: Workspace identifier whose routing is updated.
        values: Routing fields to validate and save.
        expected_revision: Current settings revision required for the update.

    Returns:
        The new settings revision and normalized routing values.

    Raises:
        AgentError: If task assignments or profile references are invalid.
    """
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


def authorize_provider(store: Store, policy: AccessPolicy, workspace: str, profile: Profile) -> None:
    """Require launch approval for the provider origin and credential reference.

    Args:
        store: Workspace store used to read privacy settings.
        policy: Launch policy containing allowed provider origins and credentials.
        workspace: Workspace identifier owning the request.
        profile: Provider profile to authorize.

    Raises:
        AgentError: If network access, endpoint origin, credentials, or workspace privacy is disallowed.
    """
    policy.require('network')
    if origin(profile.base_url) not in {origin(url) for url in policy.allowed_llm_origins}:
        raise AgentError('network_not_allowed', 'Provider origin is not explicitly allowed for this launch')
    if profile.key_env and profile.key_env not in policy.allowed_credential_refs:
        raise AgentError('credential_unavailable', 'Named credential reference is not approved for this launch')
    if not is_local(profile.base_url) and not store.setting(workspace, 'external_llm', False):
        raise AgentError('network_not_allowed', 'Workspace external requests are disabled')


class ProviderOperations:
    """Implement provider profile, routing, and process-local connection operations."""

    def _runtime_manager(self, w: str, profile_id: str, profile: Profile) -> RuntimeConnections | None:
        """Return the matching runtime credential manager, clearing stale bindings.

        Args:
            w: Workspace identifier owning the runtime binding.
            profile_id: Provider profile identifier.
            profile: Current provider profile configuration.

        Returns:
            The matching process-local connection manager, if it is still current.
        """
        key = (w, profile_id)
        manager = self.runtime_connections.get(key)
        if manager is not None and self.runtime_profiles.get(key) != runtime_profile(profile):
            invalidated_override = ('DATAFORGE_RUNTIME_CREDENTIAL' in manager._credentials and
                json.loads(self.runtime_profiles.get(key) or '{}').get('key_env') == profile.key_env)
            manager.clear()
            if invalidated_override:
                manager.disconnect(profile.key_env)
            if profile.key_env in manager._disconnected:
                self.runtime_profiles[key] = runtime_profile(profile)
                return manager
            self.runtime_connections.pop(key, None)
            self.runtime_profiles.pop(key, None)
            return None
        return manager

    def _public_profile(self, profile: Profile) -> dict[str, Any]:
        """Return profile settings with unapproved credential references removed.

        Args:
            profile: Provider profile to expose.

        Returns:
            Public profile fields safe for the current launch policy.
        """
        data = profile.model_dump()
        if data['key_env'] not in self.policy.allowed_credential_refs:
            data['key_env'] = ''
        if data['saved_key_ref'] not in self.policy.allowed_credential_refs:
            data['saved_key_ref'] = ''
        return data

    def _providers_list(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """Return the paginated provider profiles for a workspace.

        Args:
            w: Workspace identifier.
            opts: Validated pagination options.

        Returns:
            Provider profiles and the current settings revision.
        """
        rows = self.store.rows('SELECT profile_id,config FROM llm_profiles WHERE workspace_id=? ORDER BY name,profile_id', [w])
        return self._page(w, opts, 'providers', [{'profile_id': r['profile_id'],
            'profile': self._public_profile(Profile.model_validate_json(r['config']))} for r in rows],
            settings_revision=revision(self.store, w))

    def _provider_get(self, w: str, opts: QueryOptions, profile_id: str) -> dict[str, Any]:
        """Return one workspace provider profile and its settings revision.

        Args:
            w: Workspace identifier owning the profile.
            opts: Validated operation options.
            profile_id: Provider profile identifier.

        Returns:
            The public profile and current settings revision.
        """
        return {'profile_id': profile_id, 'profile': self._public_profile(get_profile(self.store, w, profile_id)),
                'settings_revision': revision(self.store, w)}

    def _provider_save(self, w: str, opts: QueryOptions, profile: Profile | dict[str, Any],
                       expected_revision: str, profile_id: str = '') -> dict[str, Any]:
        """Save a provider profile through the shared authorization checks.

        Args:
            w: Workspace identifier receiving the profile.
            opts: Validated operation options.
            profile: Profile model or mapping to validate and save.
            expected_revision: Current settings revision required for the update.
            profile_id: Existing profile identifier, or an empty value to create one.

        Returns:
            The profile identifier and resulting settings revision.
        """
        return save_profile(self.store, self.policy, w, profile, expected_revision, profile_id)

    def _provider_remove(self, w: str, opts: QueryOptions, profile_id: str,
                         expected_revision: str) -> dict[str, Any]:
        """Remove an unused profile and clear any process-local credentials.

        Args:
            w: Workspace identifier owning the provider profile.
            opts: Validated operation options.
            profile_id: Provider profile identifier to remove.
            expected_revision: Current settings revision required for the update.

        Returns:
            Removal status and the resulting settings revision.

        Raises:
            AgentError: If routing still references the profile.
        """
        self.policy.require('config')
        check_revision(self.store, w, expected_revision)
        profile = get_profile(self.store, w, profile_id)
        route = self._routing_get(w, opts)['routing']
        if profile_id in {route['default_profile'], *route['task_models'].values(), *route['fallback_profiles']}:
            raise AgentError('conflict', 'Remove routing references before removing this profile')
        saved_ref = profile.saved_key_ref or (profile.key_env if credential_source(profile.key_env) == 'saved' else '')
        if saved_ref:
            if saved_ref not in self.policy.allowed_credential_refs:
                raise AgentError('credential_unavailable', 'Approve this saved reference at launch before deleting its profile')
            NativeCredentials().delete(self.store.home, w, profile_id, profile)
        self.store.execute('DELETE FROM llm_profiles WHERE workspace_id=? AND profile_id=?', [w, profile_id])
        manager = self.runtime_connections.pop((w, profile_id), None)
        self.runtime_profiles.pop((w, profile_id), None)
        if manager:
            manager.clear()
        return {'removed': profile_id, 'settings_revision': revision(self.store, w)}

    def _routing_get(self, w: str, opts: QueryOptions) -> dict[str, Any]:
        """Return workspace routing settings and supported task names.

        Args:
            w: Workspace identifier.
            opts: Validated operation options.

        Returns:
            Routing settings, supported task names, and the settings revision.
        """
        return {'routing': {key: self.store.setting(w, key, value) for key, value in Routing().model_dump().items()},
                'tasks': TASKS, 'settings_revision': revision(self.store, w)}

    def _routing_update(self, w: str, opts: QueryOptions, values: Routing | dict[str, Any],
                        expected_revision: str) -> dict[str, Any]:
        """Save validated provider routing for a workspace.

        Args:
            w: Workspace identifier whose routing is updated.
            opts: Validated operation options.
            values: Routing fields to validate and save.
            expected_revision: Current settings revision required for the update.

        Returns:
            The normalized routing values and resulting settings revision.
        """
        return save_routing(self.store, self.policy, w, values, expected_revision)

    def _runtime_status(self, w: str, opts: QueryOptions, profile_id: str) -> dict[str, Any]:
        """Report whether an approved runtime credential binding is active.

        Args:
            w: Workspace identifier owning the profile.
            opts: Validated operation options.
            profile_id: Provider profile identifier.

        Returns:
            Credential approval and process-local connection status.
        """
        profile = get_profile(self.store, w, profile_id)
        manager = self._runtime_manager(w, profile_id, profile)
        approved = not profile.key_env or profile.key_env in self.policy.allowed_credential_refs
        return {'profile_id': profile_id, 'reference': profile.key_env if approved else '',
                'approved': approved, 'connected': manager is not None and profile.key_env not in manager._disconnected,
                'source': credential_source(profile.key_env),
                'restart': 'Bindings last only for this owning process; UI sessions are separate'}

    def _runtime_connect(self, w: str, opts: QueryOptions, profile_id: str) -> dict[str, Any]:
        """Bind an approved launch credential to the current process.

        Args:
            w: Workspace identifier owning the provider profile.
            opts: Validated operation options.
            profile_id: Provider profile identifier to connect.

        Returns:
            Runtime connection status after binding the credential.

        Raises:
            AgentError: If the endpoint or referenced credential is not authorized or available.
        """
        profile = get_profile(self.store, w, profile_id)
        authorize_provider(self.store, self.policy, w, profile)
        manager = RuntimeConnections().for_workspace(self.store.home, w).for_profile(profile_id, profile)
        secret = manager.resolve(profile.key_env)
        if profile.key_env and not secret:
            manager.clear()
            raise AgentError('credential_unavailable', 'Approved launch reference is unavailable')
        # Internal alias supports legacy launch names without mutating environment or saved profiles.
        if secret and credential_source(profile.key_env) != 'saved':
            manager.register('DATAFORGE_RUNTIME_CREDENTIAL', secret)
        manager._request_secrets.clear()
        self.runtime_connections[(w, profile_id)] = manager
        self.runtime_profiles[(w, profile_id)] = runtime_profile(profile)
        return self._runtime_status(w, opts, profile_id)

    def _runtime_clear(self, w: str, opts: QueryOptions, profile_id: str) -> dict[str, Any]:
        """Clear a runtime credential binding and return the resulting status.

        Args:
            w: Workspace identifier owning the profile.
            opts: Validated operation options.
            profile_id: Provider profile identifier.

        Returns:
            Credential approval and process-local connection status after clearing.
        """
        profile = get_profile(self.store, w, profile_id)
        manager = self.runtime_connections.pop((w, profile_id), None)
        self.runtime_profiles.pop((w, profile_id), None)
        if manager:
            manager.clear()
        if credential_source(profile.key_env) == 'saved':
            manager = RuntimeConnections()
            manager.disconnect(profile.key_env)
            self.runtime_connections[(w, profile_id)] = manager
            self.runtime_profiles[(w, profile_id)] = runtime_profile(profile)
        return self._runtime_status(w, opts, profile_id)

    def _provider_operation(self, w: str, opts: QueryOptions, profile_id: str,
                            operation: str) -> dict[str, Any]:
        """Run model discovery or a provider connection check under request limits.

        Args:
            w: Workspace identifier owning the provider profile.
            opts: Validated operation options.
            profile_id: Provider profile identifier to use.
            operation: Provider action, either model discovery or a connection check.

        Returns:
            Sanitized operation result with its duration.

        Raises:
            AgentError: If authorization fails, request capacity is unavailable, or the provider operation fails.
        """
        profile = get_profile(self.store, w, profile_id)
        authorize_provider(self.store, self.policy, w, profile)
        recipient_profile = profile
        manager = (self._runtime_manager(w, profile_id, profile) or RuntimeConnections()).for_workspace(
            self.store.home, w).for_profile(profile_id, profile)
        if manager.registered('DATAFORGE_RUNTIME_CREDENTIAL'):
            profile = profile.model_copy(update={'key_env': 'DATAFORGE_RUNTIME_CREDENTIAL'})
        try:
            if profile.key_env and not manager.resolve(profile.key_env):
                raise AgentError('credential_unavailable', 'Selected credential is unavailable; reconnect or choose session-only storage')
        except CredentialError as exc:
            raise AgentError('credential_unavailable', str(exc)) from None
        resources = LLMResourceSettings.model_validate({k: self.store.setting(w, k, v) for k, v in LLMResourceSettings().model_dump().items()})
        started = time.perf_counter()
        try:
            with connection_scope(manager), request_slot(self.store.home, w, resources.llm_concurrency), Adapter(profile, self.provider_transport) as adapter:
                if operation == 'models':
                    catalog = adapter.model_catalog()
                    models = [item.id for item in catalog]
                    result = self._page(w, opts, ['models', profile_id], models)
                    result['selected_model_capabilities'] = next((bind_capabilities(item.capabilities, recipient_profile).model_dump()
                        for item in catalog if item.id == profile.model), None)
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

    def _provider_models(self, w: str, opts: QueryOptions, profile_id: str) -> dict[str, Any]:
        """List models through the authorized provider operation path.

        Args:
            w: Workspace identifier owning the profile.
            opts: Validated pagination options.
            profile_id: Provider profile identifier.

        Returns:
            Paginated model identifiers.
        """
        return self._provider_operation(w, opts, profile_id, 'models')

    def _provider_test(self, w: str, opts: QueryOptions, profile_id: str) -> dict[str, Any]:
        """Check provider connectivity through the authorized operation path.

        Args:
            w: Workspace identifier owning the profile.
            opts: Validated operation options.
            profile_id: Provider profile identifier.

        Returns:
            Connection status and provider usage metadata.
        """
        return self._provider_operation(w, opts, profile_id, 'test')
