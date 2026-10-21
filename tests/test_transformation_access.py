"""All access surfaces preserve column identity, coverage and source restrictions."""
import asyncio
import json
import os
import sys
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError, compact
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app as cli
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store

SQL = (b"create table stage.totals as select o.quantity * o.price as gross, 42 as fixed "
       b"from raw.orders o where o.active = 1;\n"
       b"create table mart.totals as select gross + 1 as total, fixed from stage.totals;")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Any]:
    """Provide the engine fixture used by the tests.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path / "home")
    workspace = store.create_workspace("Transformation access")
    Importer(store, workspace).files([("totals.sql", SQL)], {".sql"})
    analyze(store, workspace)
    service = AgentService(store)
    yield service, store, workspace
    service.close()
    store.close()


def test_catalog_trace_paging_and_source_gate(engine: Any) -> None:
    """Verify that catalog trace paging and source gate.

    Args:
        engine: Engine instance exercised by the test.
    """
    service, store, w = engine
    catalog = service.call("column_catalog", w, asset="mart.totals")
    target = next(c for c in catalog["items"] if c["column_name"] == "total")
    summary = service.call("column_lineage", w, asset="mart.totals", column=target["column_id"])
    assert summary["state"] == "known" and len(summary["items"]) >= 2
    assert all("expression" not in d and "code" not in d["evidence"] for d in summary["items"])
    assert all(d["paths"] for d in summary["items"])
    verified = service.call("column_lineage", w, asset="mart.totals", column="total", status="verified")
    assert verified["items"] and all(d["status"] == "verified" for d in verified["items"])
    page = service.call("column_lineage", w, asset="mart.totals", column="total", options={"limit": 1})
    assert page["next_cursor"] and not page["complete"]
    following = service.call("column_lineage", w, asset="mart.totals", column="total",
                             options={"limit": 1, "cursor": page["next_cursor"]})
    assert page["items"][0]["derivation_id"] != following["items"][0]["derivation_id"]
    with pytest.raises(AgentError, match="Cursor"):
        service.call("column_lineage", w, asset="mart.totals", column="total", direction="downstream",
                     options={"cursor": page["next_cursor"]})
    detailed = service.call("column_lineage", w, asset="mart.totals", column="total",
                            options={"detail_level": "detailed", "max_chars": 30000})
    assert any(d["evidence"].get("code") for d in detailed["items"])
    store.set_setting(w, "agent_access", {"allow_source": False})
    standard = service.call("column_lineage", w, asset="mart.totals", column="total",
                            options={"detail_level": "standard"})
    assert all("expression" not in d and "code" not in d["evidence"] for d in standard["items"])
    with pytest.raises(AgentError):
        service.call("column_lineage", w, asset="mart.totals", column="total", options={"detail_level": "detailed"})


def test_scope_constants_limits_and_mcp_parity(engine: Any) -> None:
    """Verify that scope constants limits and mcp parity.

    Args:
        engine: Engine instance exercised by the test.
    """
    service, store, w = engine
    constant = service.call("column_lineage", w, asset="stage.totals", column="fixed")
    assert constant["state"] == "constant"
    assert all(i["role"] in {"row_filter", "join"}
               for i in constant["items"][0]["inputs"])
    limited = service.call("column_lineage", w, asset="mart.totals", column="total",
                           options={"max_depth": 1, "max_items": 1, "max_chars": 4000})
    assert len(limited["items"]) <= 1 and not limited["complete"]
    assert len(compact(limited)) <= 4000
    restricted = AgentService(store, AccessPolicy(workspaces=(w,)))
    other = store.create_workspace("Other")
    try:
        with pytest.raises(AgentError):
            restricted.call("column_lineage", other, asset="mart.totals", column="total")
        with pytest.raises(AgentError):
            restricted.call("column_catalog", other, asset="mart.totals")
    finally:
        restricted.close()
    server = create_server(service)

    async def check() -> None:
        """Handle check for the test scenario."""
        tools = {t.name: t for t in await server.list_tools()}
        for name in ("get_column_lineage", "get_transformation_columns"):
            assert tools[name].annotations.readOnlyHint
        arguments = {"workspace_id": w, "asset": "mart.totals", "column": "total"}
        actual = await server.call_tool("get_column_lineage", arguments)
        assert not actual.isError
        assert actual.structuredContent == service.call("column_lineage", w, asset="mart.totals", column="total")
        actual_catalog = await server.call_tool("get_transformation_columns", {"workspace_id": w, "asset": "mart.totals"})
        assert actual_catalog.structuredContent == service.call("column_catalog", w, asset="mart.totals")
    asyncio.run(check())


def test_column_cli_matches_service(tmp_path: Path) -> None:
    """Verify that column cli matches service.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    home = tmp_path / "cli"
    store = Store(home)
    w = store.create_workspace("CLI transformations")
    Importer(store, w).files([("totals.sql", SQL)], {".sql"})
    analyze(store, w)
    service = AgentService(store)
    expected = service.call("column_lineage", w, asset="mart.totals", column="total")
    service.close()
    store.close()
    result = CliRunner().invoke(cli, ["--home", str(home), "--json", "columns", "lineage", "mart.totals", "total", "-w", w])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == expected
    catalog = CliRunner().invoke(cli, ["--home", str(home), "--json", "columns", "catalog", "mart.totals", "-w", w])
    assert catalog.exit_code == 0, catalog.output
    assert "total" in {c["column_name"] for c in json.loads(catalog.output)["items"]}


def test_column_tools_through_real_stdio_transport(tmp_path: Path) -> None:
    """Verify that column tools through real stdio transport.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    w = store.create_workspace('Wire transformations')
    Importer(store, w).files([('totals.sql', SQL)], {'.sql'})
    analyze(store, w)
    service = AgentService(store)
    expected = service.call('column_lineage', w, asset='mart.totals', column='total')
    service.close()
    store.close()

    async def check() -> None:
        """Handle check for the test scenario."""
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'dataforge.cli', '--home', str(tmp_path), 'mcp'], env={**os.environ})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                catalog = await session.call_tool('get_transformation_columns',
                    {'workspace_id': w, 'asset': 'mart.totals'})
                assert not catalog.isError
                assert 'total' in {c['column_name'] for c in catalog.structuredContent['items']}
                trace = await session.call_tool('get_column_lineage',
                    {'workspace_id': w, 'asset': 'mart.totals', 'column': 'total'})
                assert not trace.isError and trace.structuredContent == expected
    asyncio.run(check())


def test_transformation_ui_native_flow_and_workspace_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that transformation ui native flow and workspace context.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from ui.common import get_store

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path / "ui"))
    store = get_store(str(tmp_path / "ui"))
    w = store.create_workspace("UI transformations")
    Importer(store, w).files([("totals.sql", SQL)], {".sql"})
    analyze(store, w)
    view = AppTest.from_file(Path("app.py").resolve(), default_timeout=30).run()
    view.switch_page("ui/pages/transformations.py").run()
    assert not view.exception and view.title[0].value == "Transformation lineage"
    asset = next(a["asset_id"] for a in store.assets(w) if a["name"] == "mart.totals")
    next(s for s in view.selectbox if s.label == "Choose an exact asset").set_value(asset).run()
    next(t for t in view.text_input if t.label == "Column name or exact ID").set_value("total").run()
    assert not view.exception
    assert any(s.label == "Transformation depth" for s in view.slider)
    assert any("Output" in frame.value.columns for frame in view.dataframe)
    assert view.get("popover")
    assert {d.proto.label for d in view.get("download_button")} >= {"Download JSON", "Download CSV"}
    assert not view.code  # Original source is loaded only inside the evidence inspector.
    view.session_state["transformation_inspector_" + w + "_" + asset] = True
    view.session_state["transformation_step_" + w + "_" + asset] = 999
    from dataforge.transformations import column_catalog

    def changed_column_ids(*args: Any, **kwargs: Any) -> Any:
        """Handle changed column ids for the test scenario.

        Args:
            args: Positional arguments forwarded to the operation.
            kwargs: Keyword arguments forwarded to the operation.

        Returns:
            Value produced for the test scenario.
        """
        return [{**row, "column_id": "revision-" + row["column_id"]} for row in column_catalog(*args, **kwargs)]

    monkeypatch.setattr("dataforge.transformations.column_catalog", changed_column_ids)
    view.run()
    assert not view.exception and any("gross + 1" in code.value for code in view.code)
    assert view.session_state["transformation_column_" + w + "_" + asset].startswith("revision-")
    other = store.create_workspace("Empty workspace")
    view.run()
    view.selectbox(key="workspace").set_value(other).run()
    assert not view.exception and not view.code
    assert not any(s.label == "Column to trace" for s in view.selectbox)
