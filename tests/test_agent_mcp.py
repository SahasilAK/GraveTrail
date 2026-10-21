import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server, http_app
from dataforge.agent.service import AgentService
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_mcp_service_parity_resources_prompts_and_errors(tmp_path: Path) -> None:
    """Verify that mcp service parity resources prompts and errors.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    w = store.create_workspace("MCP")
    Importer(store, w).files([("a.sql", b"create table pub.x as select id from raw.x;")], {".sql"})
    analyze(store, w)
    service = AgentService(store)
    server = create_server(service)
    assert server.name == "GraveTrail"

    async def check() -> None:
        """Handle check for the test scenario."""
        names = {t.name for t in await server.list_tools()}
        assert {"get_lineage", "get_source_evidence", "get_job_status", "export_results"} <= names
        result = await server.call_tool("get_lineage", {"workspace_id": w, "asset": "pub.x"})
        assert result.structuredContent == service.call("lineage", w, asset="pub.x")
        assert result.content == []  # Structured data has one representation on the wire.
        denied = await server.call_tool("start_lineage_analysis", {"workspace_id": w})
        assert denied.isError and denied.structuredContent["error"]["code"] == "forbidden"
        templates = await server.list_resource_templates()
        assert any("summary" in str(t.uriTemplate) for t in templates)
        resource = await server.read_resource(f"dataforge://workspaces/{w}/summary")
        assert json.loads(list(resource)[0].content)["workspace_id"] == w
        renamed = await server.read_resource(f"gravetrail://workspaces/{w}/summary")
        assert list(renamed)[0].content == list(resource)[0].content
        for scheme in ("gravetrail", "dataforge"):
            listing = await server.read_resource(f"{scheme}://workspaces")
            assert json.loads(list(listing)[0].content)["items"][0]["workspace_id"] == w
        prompts = await server.list_prompts()
        assert any(p.name == "investigate_lineage" for p in prompts)
    try:
        asyncio.run(check())
    finally:
        service.close()
        store.close()


def test_stdio_real_client_without_streamlit(tmp_path: Path) -> None:
    """Verify that stdio real client without streamlit.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    async def check() -> None:
        """Handle check for the test scenario."""
        params = StdioServerParameters(command=sys.executable, args=["-m", "dataforge.cli", "--home", str(tmp_path), "mcp"],
                                      env={**os.environ})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=10)) as session:
                await session.initialize()
                result = await session.call_tool("list_workspaces", {})
                assert not result.isError and result.structuredContent["count"] == 0
                capabilities = await session.call_tool('get_capabilities', {})
                assert not capabilities.isError and capabilities.structuredContent['total'] == 49
    asyncio.run(check())


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


def test_mcp_polling_remains_responsive_while_another_query_waits(tmp_path: Path) -> None:
    """Verify that mcp polling remains responsive while another query waits.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    import threading

    store = Store(tmp_path)
    w = store.create_workspace("responsive")
    store.rows("SELECT ? AS ready", ["ready"])
    service = AgentService(store)
    server = create_server(service)
    record = service.jobs.create(w, "ingest")
    entered, release = threading.Event(), threading.Event()

    def transaction() -> None:
        """Handle transaction for the test scenario."""
        with store.transaction():
            entered.set()
            release.wait(5)

    thread = threading.Thread(target=transaction)
    thread.start()
    assert entered.wait(5)
    timer = threading.Timer(1, release.set)
    timer.start()

    async def check() -> None:
        """Handle check for the test scenario."""
        waiting = asyncio.create_task(server.call_tool("search_assets", {"workspace_id": w}))
        await asyncio.sleep(.05)
        try:
            result = await server.call_tool("get_job_status", {"workspace_id": w, "job_id": record["job_id"]})
            assert not result.isError and not release.is_set()
        finally:
            release.set()
            await waiting
    try:
        asyncio.run(check())
    finally:
        timer.cancel()
        release.set()
        thread.join(5)
        service.close()
        store.close()
