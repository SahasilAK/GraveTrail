import asyncio
import os
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server, http_app
from dataforge.agent.service import AgentService
from dataforge.store import Store


def test_http_requires_token_scope_and_secure_remote_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that http requires token scope and secure remote configuration.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    store = Store(tmp_path)
    w = store.create_workspace("HTTP")
    service = AgentService(store, AccessPolicy(workspaces=(w,)))
    server = create_server(service)
    monkeypatch.delenv("DATAFORGE_MCP_TOKEN", raising=False)
    with pytest.raises(AgentError):
        http_app(server, service.policy)
    monkeypatch.setenv("DATAFORGE_MCP_TOKEN", "test-only-credential-" + "x" * 40)
    with pytest.raises(AgentError):
        http_app(server, AccessPolicy())
    with pytest.raises(AgentError):
        http_app(server, service.policy, host="0.0.0.0", public_url="http://example.com/mcp")
    application = http_app(server, service.policy)

    async def check() -> None:
        """Handle check for the test scenario."""
        async with server.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://127.0.0.1:8765") as client:
                for method in ("get", "post", "delete"):
                    response = await getattr(client, method)("/mcp")
                    assert response.status_code == 401
                    assert "x" * 40 not in response.text
                client.headers["Authorization"] = "Bearer " + os.environ["DATAFORGE_MCP_TOKEN"]
                oversized = await client.post('/mcp', content=b' ' * 70000,
                    headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
                assert oversized.status_code == 413
                async with streamable_http_client("http://127.0.0.1:8765/mcp", http_client=client) as (read, write, _):
                    async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=10)) as session:
                        await session.initialize()
                        result = await session.call_tool("get_workspace_summary", {"workspace_id": w})
                        assert result.structuredContent["workspace_id"] == w and not result.isError
                        settings = await session.call_tool('get_workspace_settings', {'workspace_id': w, 'section': 'resources'})
                        assert not settings.isError and settings.structuredContent['values']['max_files'] == 10000
                        denied = await session.call_tool('update_workspace_settings', {'workspace_id': w, 'section': 'resources',
                            'values': {'max_files': 20}, 'expected_revision': settings.structuredContent['settings_revision']})
                        assert denied.isError and denied.structuredContent['error']['code'] == 'forbidden'
    try:
        asyncio.run(check())
    finally:
        service.close()
        store.close()
