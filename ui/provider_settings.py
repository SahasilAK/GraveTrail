"""Provider profiles and task routing. Secrets remain environment references."""
import json
import uuid

import streamlit as st

from dataforge.configuration import LLMResourceSettings
from dataforge.connections import DEFAULT_KEY_ENV, current_connections
from dataforge.llm import PROVIDERS, TASKS, Adapter, Profile, is_local, response_object
from dataforge.llm_resources import request_slot


def render(store, workspace):
    profiles = store.rows("SELECT * FROM llm_profiles WHERE workspace_id=? ORDER BY name", [workspace])
    names = {p["profile_id"]: p["name"] for p in profiles}
    selection = st.selectbox("Provider profile", ["New profile", *names], format_func=lambda x: names.get(x, x))
    existing = next((p for p in profiles if p["profile_id"] == selection), None)
    config = json.loads(existing["config"]) if existing else {}
    provider = st.selectbox("Provider", list(PROVIDERS), index=list(PROVIDERS).index(config.get("provider", "Ollama")))
    with st.form("provider_config"):
        name = st.text_input("Profile name", config.get("name", provider))
        url = st.text_input("API base URL", config.get("base_url", PROVIDERS[provider]))
        model = st.text_input("Model or deployment identifier", config.get("model", ""), help="Use model discovery below or enter an identifier available to your account.")
        key_env = st.text_input("Credential environment variable name", config.get("key_env", DEFAULT_KEY_ENV[provider]), placeholder="e.g. DATAFORGE_OPENAI_API_KEY")
        st.caption("Store only the variable name here. Set its secret value in the process environment before launching the app.")
        auths = ["auto", "none", "bearer", "api-key", "x-api-key", "x-goog-api-key"]
        auth = st.selectbox("Authentication", auths, index=auths.index(config.get("auth", "auto")))
        timeout = st.number_input("Request timeout (seconds)", 1, 180, int(config.get("timeout", 30)))
        retries = st.number_input("Retries for rate limits and transient failures", 0, 2, int(config.get("retries", 1)))
        max_tokens = st.number_input("Maximum output tokens", 64, 32000, int(config.get("max_tokens", 2048)))
        context = st.number_input("Profile source context character limit", 500, 200000, int(config.get("context_chars", 16000)))
        temperature_enabled = st.checkbox("Send temperature parameter", value=config.get("temperature") is not None)
        temperature = st.number_input("Temperature", 0., 2., float(config.get("temperature") or 0.), step=.1)
        structured = st.checkbox("Request JSON output where supported", value=config.get("structured", True))
        api_version = st.text_input("Azure API version", config.get("api_version", "2024-10-21"))
        saved = st.form_submit_button("Save provider profile", type="primary")
    if saved:
        try:
            profile = Profile(provider=provider, name=name, base_url=url, model=model, key_env=key_env, auth=auth,
                timeout=timeout, retries=retries, max_tokens=max_tokens, context_chars=context,
                temperature=temperature if temperature_enabled else None, structured=structured, api_version=api_version)
            pid = selection if existing else uuid.uuid4().hex
            store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?) ON CONFLICT(profile_id) DO UPDATE SET name=excluded.name,config=excluded.config",
                          [pid, workspace, name, profile.model_dump_json()])
            st.success("Provider profile saved")
            st.rerun()
        except ValueError:
            st.error("Profile configuration is invalid. Check the endpoint, model and environment variable name.")
    if existing:
        profile = Profile.model_validate(config)
        manager = current_connections()
        st.caption("Credentials are retained only for the active runtime and are not saved in application files or databases. They may need to be re-entered when the application restarts.")
        st.caption("Credential status: " + ("available" if manager.resolve(profile.key_env) else "disconnected / optional for local endpoints"))
        def connect():
            try:
                manager.register(profile.key_env, st.session_state.pop('runtime_secret', ''))
            except ValueError:
                st.session_state['connection_notice'] = 'Use a DATAFORGE_ variable name and a nonempty credential.'
        st.text_input("Runtime credential", type="password", key="runtime_secret")
        st.button("Connect for this session", on_click=connect)
        if st.button("Clear runtime credentials"):
            manager.clear()
            st.session_state.pop('runtime_secret', None)
            st.rerun()
        if notice := st.session_state.pop('connection_notice', None):
            st.warning(notice)
        with st.container(horizontal=True):
            discover = st.button("Discover models")
            test = st.button("Test model connection")
            remove = st.button("Remove profile")
        if remove:
            store.execute("DELETE FROM llm_profiles WHERE workspace_id=? AND profile_id=?", [workspace, selection])
            st.rerun()
        if discover or test:
            try:
                if not is_local(profile.base_url) and not store.setting(workspace, "external_llm", False):
                    raise ValueError("Enable external requests in Security and privacy first")
                resources = LLMResourceSettings.model_validate({k: store.setting(workspace, k, v)
                    for k, v in LLMResourceSettings().model_dump().items()})
                with request_slot(store.home, workspace, resources.llm_concurrency), Adapter(profile) as adapter:
                    if discover:
                        st.write(adapter.models())
                    else:
                        response, usage = adapter.complete('Return a JSON object with key "status".', 'Return {"status":"connected"}.')
                        obj = response_object(response)
                        if obj.get("status") != "connected":
                            raise ValueError("Endpoint responded but did not follow the connection-test JSON contract")
                        st.success("Model connection validated")
                        st.json(usage)
            except Exception as exc:
                message = "LLM requests are busy; retry after an active request finishes." if isinstance(exc, ValueError) and 'requests are busy' in str(exc) else "Check runtime credentials, endpoint and privacy settings."
                st.error(f"Connection check failed ({type(exc).__name__}). {message}")
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
                store.set_setting(workspace, "default_profile", default)
                store.set_setting(workspace, "task_models", selected)
                store.set_setting(workspace, "fallback_profiles", fallbacks)
                st.success("Task routing saved")
    st.caption("Databricks Model Serving uses the serving endpoint API. Genie is a separate query agent and is not treated as a chat model. Codex/ChatGPT sign-in is not used as an application API credential.")
