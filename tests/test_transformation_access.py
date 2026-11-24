"""All access surfaces preserve column identity, coverage and source restrictions."""
import asyncio
import base64
import csv
import io
import os
import sys
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.service import AgentService
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
    schema = b'create table raw.orders (quantity int, price int, active int, notes varchar(25));'
    Importer(store, workspace).files([('schema.sql', schema), ('totals.sql', SQL)], {'.sql'})
    analyze(store, workspace)
    service = AgentService(store, AccessPolicy(allow_write=True))
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

    result = service.call('columns', w, asset='raw.orders', column_query=' quantity, price ')
    assert {r['column_name'] for r in result['items']} == {'quantity', 'price'}
    used = service.call('columns', w, asset='raw.orders', view='used')
    assert {row['column_name'] for row in used['items']} == {'active', 'price', 'quantity'}
    unused = service.call('columns', w, asset='raw.orders', view='unused')
    assert unused['names_available'] and unused['items'] == [{'column_name': 'notes'}]

    def export_rows(kind, selection):
        artifact = service.call('artifact_create', w, kind=kind, format='csv', selection=selection)
        content = service.call('artifact_read', w, artifact_id=artifact['artifact_id'])
        return artifact['artifact_id'], list(csv.DictReader(io.StringIO(base64.b64decode(content['data']).decode())))

    _, columns = export_rows('columns', {'asset': 'raw.orders', 'query': 'price, quantity'})
    assert {r['column_name'] for r in columns} == {'quantity', 'price'}
    artifact, trace = export_rows('column-lineage', {'asset': 'mart.totals', 'column': 'total'})
    assert trace and all(r['column'] == 'total' and r['run_id'] for r in trace)
    assert any('gross + 1' in r['expression'] for r in trace)

    store.set_setting(w, "agent_access", {"allow_source": False})
    standard = service.call("column_lineage", w, asset="mart.totals", column="total",
                            options={"detail_level": "standard"})
    assert all("expression" not in d and "code" not in d["evidence"] for d in standard["items"])
    with pytest.raises(AgentError):
        service.call("column_lineage", w, asset="mart.totals", column="total", options={"detail_level": "detailed"})
    with pytest.raises(AgentError, match='Source'):
        service.call('artifact_read', w, artifact_id=artifact)


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
                workspaces = await session.call_tool('list_workspaces', {})
                assert not workspaces.isError
                assert {row['workspace_id'] for row in workspaces.structuredContent['items']} == {w}
                capabilities = await session.call_tool('get_capabilities', {})
                assert not capabilities.isError and capabilities.structuredContent['total'] > 0
                catalog = await session.call_tool('get_transformation_columns',
                    {'workspace_id': w, 'asset': 'mart.totals'})
                assert not catalog.isError
                assert 'total' in {c['column_name'] for c in catalog.structuredContent['items']}
                trace = await session.call_tool('get_column_lineage',
                    {'workspace_id': w, 'asset': 'mart.totals', 'column': 'total'})
                assert not trace.isError and trace.structuredContent == expected
    asyncio.run(check())
