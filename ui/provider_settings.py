"""Provider profiles and task routing. Secrets remain environment references."""
import json

import streamlit as st

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.configuration import LLMResourceSettings
from dataforge.connections import DEFAULT_KEY_ENV, current_connections, set_credential_environment
from dataforge.llm import PROVIDERS, TASKS, Adapter, Profile, is_local, response_object
from dataforge.llm_resources import request_slot
from dataforge.provider_service import save_profile, save_routing
from dataforge.settings_service import revision
from dataforge.store import Store


def render(store: Store, workspace: str) -> None:
    """Render provider profiles, connection checks, and task-specific routing.

    Args:
        store: Workspace storage service.
        workspace: Workspace identifier.
    """
    profiles = store.rows("SELECT * FROM llm_profiles WHERE workspace_id=? ORDER BY name", [workspace])
    names = {p["profile_id"]: p["name"] for p in profiles}
    selection = st.selectbox("Provider profile", ["New profile", *names], format_func=lambda x: names.get(x, x), key="provider_profile_" + workspace)
    existing = next((p for p in profiles if p["profile_id"] == selection), None)
    config = json.loads(existing["config"]) if existing else {}
    provider = st.selectbox("Provider", list(PROVIDERS), index=list(PROVIDERS).index(config.get("provider", "Ollama")), key=f"provider_kind_{workspace}_{selection}")
    config = config if config.get('provider') == provider else {}
    prefix = f"provider_setup_{workspace}_{selection}_{provider}"
    models_key = prefix + '_models'
    model_key = prefix + '_model'
    fetched_key = prefix + '_fetched'
    url = st.text_input("API base URL", config.get("base_url", PROVIDERS[provider]), key=prefix + '_url')

    st.subheader("Credentials")
    key_env = st.text_input("Credential environment variable name", config.get("key_env", '' if provider in {'Ollama', 'LM Studio'} else DEFAULT_KEY_ENV[provider]),
                            placeholder=DEFAULT_KEY_ENV[provider], key=prefix + '_key_env')
    st.caption("Only the variable name is saved with the profile. Use an existing environment value or enter it below.")
    manager = current_connections()
    if key_env:
        secret_key = prefix + '_environment_secret_' + key_env
        notice_key = secret_key + '_notice'

        def set_environment() -> None:
            """Set the entered credential in the process environment and clear cached models."""
            secret = st.session_state.pop(secret_key, '')
            try:
                set_credential_environment(key_env, secret)
                manager.clear(key_env)
                st.session_state.pop(models_key, None)
                st.session_state.pop(fetched_key, None)
                st.session_state[notice_key] = True
            except (ValueError, OSError):
                st.session_state[notice_key] = False

        with st.expander("Optional: Set environment variable here"):
            st.caption(f"Sets {key_env} in the running app's environment. Shared across this app's sessions until the app stops. No .env file, saved credential or log entry; the input clears on submission.")
            with st.form(secret_key + '_form'):
                st.text_input("Environment credential value (optional)", type="password", key=secret_key,
                              max_chars=16384, autocomplete="off")
                st.form_submit_button("Set environment variable", on_click=set_environment)
            notice = st.session_state.pop(notice_key, None)
            if notice is True:
                st.success("Environment variable set for the running app. Credential input cleared.")
            elif notice is False:
                st.warning("Use a DATAFORGE_ variable name and a nonempty, single-line credential without null characters. Input cleared; environment unchanged.")
    st.caption("Credential status: " + ("available" if manager.resolve(key_env) else "disconnected / optional for local endpoints"))
    with st.expander("Session-only credential (optional)"):
        def connect() -> None:
            """Register the entered credential for this browser session only."""
            try:
                manager.register(key_env, st.session_state.pop('runtime_secret', ''))
                st.session_state.pop(models_key, None)
                st.session_state.pop(fetched_key, None)
            except ValueError:
                st.session_state['connection_notice'] = 'Use a DATAFORGE_ variable name and a nonempty credential.'
        st.text_input("Runtime credential", type="password", key="runtime_secret", autocomplete="off")
        st.button("Connect for this session", on_click=connect)
        if st.button("Clear runtime credentials"):
            manager.clear()
            st.session_state.pop('runtime_secret', None)
            st.session_state.pop(models_key, None)
            st.session_state.pop(fetched_key, None)
            st.rerun()
        if notice := st.session_state.pop('connection_notice', None):
            st.warning(notice)
        st.caption("Session credentials stay in this browser session's memory until cleared. They do not change the environment.")

    with st.expander("Advanced request options"):
        auths = ["auto", "none", "bearer", "api-key", "x-api-key", "x-goog-api-key"]
        auth = st.selectbox("Authentication", auths, index=auths.index(config.get("auth", "auto")), key=prefix + '_auth')
        timeout = st.number_input("Request timeout (seconds)", 1, 180, int(config.get("timeout", 30)), key=prefix + '_timeout')
        retries = st.number_input("Retries for rate limits and transient failures", 0, 2, int(config.get("retries", 1)), key=prefix + '_retries')
        max_tokens = st.number_input("Maximum output tokens", 64, 32000, int(config.get("max_tokens", 2048)), key=prefix + '_max_tokens')
        context = st.number_input("Profile source context character limit", 500, 200000, int(config.get("context_chars", 16000)), key=prefix + '_context')
        temperature_enabled = st.checkbox("Send temperature parameter", value=config.get("temperature") is not None, key=prefix + '_send_temperature')
        temperature = st.number_input("Temperature", 0., 2., float(config.get("temperature") or 0.), step=.1, key=prefix + '_temperature')
        structured = st.checkbox("Request JSON output where supported", value=config.get("structured", True), key=prefix + '_structured')
        api_version = st.text_input("Azure API version", config.get("api_version", "2024-10-21"), key=prefix + '_api_version')
    values = dict(provider=provider, base_url=url, key_env=key_env, auth=auth, timeout=timeout,
                  retries=retries, max_tokens=max_tokens, context_chars=context,
                  temperature=temperature if temperature_enabled else None, structured=structured, api_version=api_version)
    signature = (url, key_env, auth, api_version)
    discovery = st.session_state.get(models_key, {})
    if discovery.get('signature') != signature:
        st.session_state.pop(models_key, None)
        st.session_state.pop(fetched_key, None)

    def check_connection(model: str, discover: bool) -> None:
        """Validate an endpoint and either discover models or test one model.

        Args:
            model: Model identifier used for a direct connection test.
            discover: Whether to fetch and cache the available model identifiers.
        """
        if discover:
            st.session_state.pop(models_key, None)
            st.session_state.pop(fetched_key, None)
        try:
            profile = Profile(model=model, **values)
            if not is_local(profile.base_url) and not store.setting(workspace, "external_llm", False):
                raise ValueError("Enable external requests in Connections & AI → Privacy first")
            resources = LLMResourceSettings.model_validate({k: store.setting(workspace, k, v)
                for k, v in LLMResourceSettings().model_dump().items()})
            with request_slot(store.home, workspace, resources.llm_concurrency), Adapter(profile) as adapter:
                if discover:
                    models = list(dict.fromkeys(value for value in adapter.models() if isinstance(value, str) and value))
                    st.session_state[models_key] = {'signature': signature, 'models': models}
                    st.success("Connection validated. Models fetched." if models else "Connection validated. No models listed; enter an identifier below.")
                else:
                    response, usage = adapter.complete('Return a JSON object with key "status".', 'Return {"status":"connected"}.')
                    if response_object(response).get("status") != "connected":
                        raise ValueError("Endpoint did not follow the connection-test JSON contract")
                    st.success("Model connection validated")
                    st.json(usage)
        except Exception as exc:
            message = "LLM requests are busy; retry after an active request finishes." if isinstance(exc, ValueError) and 'requests are busy' in str(exc) else "Check runtime credentials, endpoint and privacy settings."
            st.error(f"Connection check failed ({type(exc).__name__}). {message}")

    st.subheader("Test connection")
    with st.container(horizontal=True):
        test = st.button("Test connection", disabled=provider == 'Azure OpenAI')
        discover = st.button("Discover models", disabled=provider == 'Azure OpenAI')
    if provider == 'Azure OpenAI':
        st.caption("Azure deployment discovery requires a separate management API. Enter a deployment below and use Test model connection.")
    else:
        st.caption("Checks the endpoint and credential and fetches available models. No saved profile or selected model is needed.")
    if test or discover:
        check_connection('connection-check', True)

    st.subheader("Model")
    models = st.session_state.get(models_key, {}).get('models', [])
    if models:
        def select_model() -> None:
            """Copy the selected discovered model into the model text field."""
            selected = st.session_state.get(fetched_key)
            if selected in models:
                st.session_state[model_key] = selected
        st.selectbox("Fetched models", models, index=None, key=fetched_key,
                     placeholder="Select a fetched model", on_change=select_model)
    model = st.text_input("Model or deployment identifier", config.get("model", ""), key=model_key,
                          help="Select a fetched model above or type an identifier available to your account.")
    if st.button("Test model connection", disabled=not model):
        check_connection(model, False)
    name = st.text_input("Profile name", config.get("name", provider), key=prefix + '_name')
    if st.button("Save provider profile", type="primary"):
        try:
            profile = Profile(name=name, model=model, **values)
            policy = AccessPolicy(allow_write=True, allow_config_write=True, allowed_credential_refs=(key_env,) if key_env else ())
            with store.lock:
                save_profile(store, policy, workspace, profile.model_dump(), revision(store, workspace), selection if existing else '')
            st.success("Provider profile saved")
            st.rerun()
        except (ValueError, AgentError):
            st.error("Profile configuration is invalid. Check the endpoint, model and environment variable name.")
    if existing and st.button("Remove profile"):
        store.execute("DELETE FROM llm_profiles WHERE workspace_id=? AND profile_id=?", [workspace, selection])
        st.rerun()
    if names:
        st.subheader("Task-specific model routing")
        with st.form("task_routing"):
            ids = list(names)
            default_id = store.setting(workspace, "default_profile", ids[0])
            default = st.selectbox("Default profile", ids, index=ids.index(default_id) if default_id in ids else 0, format_func=names.get)
            assignments = store.setting(workspace, "task_models", {})
            selected = {}
            for task in TASKS:
                value = assignments.get(task, "")
                selected[task] = st.selectbox(task.replace("_", " ").capitalize(), ["", *ids],
                    index=(["", *ids].index(value) if value in ids else 0), format_func=lambda k: names.get(k, "Use default"))
            fallbacks = st.multiselect("Ordered fallback profiles", ids,
                default=[x for x in store.setting(workspace, "fallback_profiles", []) if x in ids], format_func=names.get)
            st.caption("Fallback applies only to transient failures and profiles on the same recipient host. Malformed/unsupported output is quarantined.")
            if st.form_submit_button("Save model routing"):
                save_routing(store, AccessPolicy(allow_write=True, allow_config_write=True), workspace,
                    {'default_profile': default, 'task_models': selected, 'fallback_profiles': fallbacks}, revision(store, workspace))
                st.success("Task routing saved")
    st.caption("Databricks Model Serving uses the serving endpoint API. Genie is a separate query agent and is not treated as a chat model. Codex/ChatGPT sign-in is not used as an application API credential.")
