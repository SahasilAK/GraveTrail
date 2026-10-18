"""Human-facing setup and workspace access controls for the shared automation services."""
import asyncio
import json
import sys

import streamlit as st

from dataforge.agent.contracts import AgentError, AgentSettings
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.settings_service import save_ui_settings


def render(store, workspace):
    st.subheader("Agent & Automation Access")
    st.markdown("Use GraveTrail from scripts or an AI assistant. Analysis runs locally; normal agent queries use stored results and do not call an LLM.")
    settings = AgentSettings.from_store(store, workspace)
    with st.form("agent_access_" + workspace):
        enabled = st.checkbox("Enable agent access for this workspace", settings.enabled)
        writes = st.checkbox("Permit explicitly authorized agent mutations", settings.allow_write,
            help="The CLI or MCP server must also be launched with --allow-write. This includes imports, analysis and export artifact creation.")
        source = st.checkbox("Allow source retrieval", settings.allow_source,
            help="Allows explicitly requested statements, file lines, detailed responses and export retrieval.")
        levels = ["summary", "standard", "detailed"]
        detail = st.selectbox("Default agent response detail", levels, index=levels.index(settings.default_detail))
        budget = st.number_input("Maximum agent response characters", 512, 100000, settings.max_chars, step=512)
        logging = st.checkbox("Audit read operations", settings.audit_reads,
            help="Mutations are always audited locally. Audit records contain action, workspace, time and outcome; no source, arguments or credentials.")
        if st.form_submit_button("Save agent access settings"):
            values = AgentSettings(enabled=enabled, allow_write=writes, allow_source=source,
                                   default_detail=detail, max_chars=budget, audit_reads=logging)
            save_ui_settings(store, workspace, 'agent_access', values.model_dump())
            st.session_state["settings_notice_" + workspace] = "Agent access settings saved"
            st.rerun()

    st.caption("Disabling access rejects subsequent requests for this workspace. It does not start or stop a server process. Jobs already running may finish. Agent access defaults to read-only at launch.")
    st.subheader("Install and use the CLI")
    st.code("uv sync --locked --extra dev\nuv run gravetrail --help", language="bash")
    st.code(f'gravetrail --home "{store.home}" --json workspace list\n'
            f'gravetrail --home "{store.home}" --json lineage upstream pub.all_kpis --workspace {workspace}', language="bash")
    st.info("DuckDB permits one owning process per data home. Stop this Streamlit process before a separate CLI/MCP process opens the same home, or use a separate home. Within the MCP process, tools share the same store and managed jobs.")
    st.subheader("Connect a local MCP client")
    args = ["-m", "dataforge.cli", "--home", str(store.home), "--allowed-workspace", workspace, "mcp"]
    st.caption("Local stdio is recommended. The client launches the server; no port or credential is needed. These examples grant access only to the active workspace.")
    st.markdown("**Codex — `config.toml`**")
    st.code("[mcp_servers.gravetrail]\ncommand = " + json.dumps(sys.executable) + "\nargs = " + json.dumps(args), language="toml")
    st.markdown("**Claude Code — project `.mcp.json`**")
    st.code(json.dumps({"mcpServers": {"gravetrail": {"command": sys.executable, "args": args}}}, indent=2), language="json")
    st.caption("Use the examples with a trusted client. Add --allow-write before mcp and configure DATAFORGE_ALLOWED_ROOTS only when imports or analysis should be allowed.")
    st.markdown("Configuration references: [Codex MCP](https://developers.openai.com/codex/mcp) · [Claude Code MCP](https://code.claude.com/docs/en/mcp).")

    st.subheader("Network access and authentication")
    st.markdown("Streamable HTTP is optional. Set a private token of at least 32 characters in the named environment variable `DATAFORGE_MCP_TOKEN` before launch. Clients send it in the Authorization bearer header. Credentials are never saved by these settings.")
    st.code(f'gravetrail --home "{store.home}" --allowed-workspace {workspace} mcp '
            '--transport streamable-http --host 127.0.0.1 --port 8765', language="bash")
    st.caption("Endpoint: http://127.0.0.1:8765/mcp. External binding also requires --public-url https://your-host/mcp behind a TLS reverse proxy. Pre-provisioned bearer credentials are supported; OAuth login/discovery is not implemented. HTTP access logging is disabled.")

    panel = st.expander("Available tools and local connection test", on_change="rerun", key="agent_tools_panel")
    if not panel.open:
        return
    with panel:
        service = AgentService(store)
        try:
            server = create_server(service)
            tools = asyncio.run(server.list_tools())
            st.code("\n".join(t.name for t in tools), language=None)
            if st.button("Test local agent access"):
                result = asyncio.run(server.call_tool("get_workspace_summary", {"workspace_id": workspace}))
                if result.isError:
                    st.error(result.structuredContent["error"]["message"])
                else:
                    st.success("Local agent access works: MCP tool schemas and shared workspace query succeeded.")
                    st.json(result.structuredContent)
        except AgentError as exc:
            st.error(str(exc))
        finally:
            service.close()
        st.caption("This checks the actual MCP handler in this process. After stopping this UI, verify the external client's stdio/HTTP connection with list_workspaces. Query tools support bounded pages; source appears only on explicit requests.")
