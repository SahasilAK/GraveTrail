from pathlib import Path
from typing import Any

import pytest

from dataforge.parsers.sas import parse_sas
from dataforge.parsers.sql import parse_sql

FIXTURES = Path(__file__).parent / "fixtures" / "vendors"


def pairs(result: Any) -> Any:
    """Handle pairs for the test scenario.

    Args:
        result: Result produced by the operation.

    Returns:
        Value produced for the test scenario.
    """
    return {(s.name, t.name) for op in result.operations for s in op.sources for t in op.targets}


def test_procedure_control_flow_never_leaks_edges() -> None:
    """Verify that procedure control flow never leaks edges.

    Args:
        body: Body value used by the test case.
    """
    body = 'BEGIN IF false THEN INSERT INTO mart.fake SELECT id FROM raw.fake; END IF; END'
    content = f"CREATE PROCEDURE mart.p() LANGUAGE SQL AS $$ {body} $$; SELECT id FROM raw.real;"
    result = parse_sql(content, "postgres")
    assert pairs(result) == set()
    assert {s.name for op in result.operations for s in op.sources} == {"raw.real"}
    assert any(d.severity != "info" for d in result.diagnostics)


def test_runtime_dynamic_sql_is_unresolved() -> None:
    """Verify that runtime dynamic sql is unresolved.

    Args:
        expression: Expression value used by the test case.
    """
    expression = "'INSERT INTO mart.x SELECT id FROM ' || source_name"
    result = parse_sql(f"EXECUTE IMMEDIATE {expression};", "snowflake")
    assert not result.operations
    assert result.diagnostics


def test_configured_macro_cannot_inject_unparsed_statements() -> None:
    """Verify that configured macro cannot inject unparsed statements."""
    result = parse_sas("data mart.x; set &source.; run;", macros={"source": "raw.a; set raw.fake;"})
    assert not pairs(result)
    assert result.diagnostics


@pytest.mark.parametrize("fixture,dialect,expected,newline", [
    ("postgres_procedure.sql", "postgres", {("raw.orders", "mart.orders"), ("mart.orders", "mart.order_audit")}, b"\r\n"),
    ("snowflake_literal.sql", "snowflake", {("raw.orders", "mart.active_orders"), ("raw.orders", "mart.order_totals")}, b"\n"),
    ("sas_macro_variables.sas", "", {("raw.orders", "mart.orders"), ("file:input/orders.csv", "work.imported")}, b"\r\n"),
])
def test_static_wrapper_persistence_cache_and_evidence(tmp_path: Path, fixture: str, dialect: str, expected: Any, newline: bytes) -> None:
    """Verify that static wrapper persistence cache and evidence.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        fixture: Fixture value used by the test case.
        dialect: Dialect selected for the test case.
        expected: Expected result for the test case.
        newline: Newline value used by the test case.
    """
    from dataforge.agent.service import AgentService
    from dataforge.graph import LineageGraph
    from dataforge.ingestion import Importer
    from dataforge.reporting import validate_lineage_evidence
    from dataforge.services import analyze, column_report
    from dataforge.store import Store

    path = FIXTURES / fixture
    original = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline)
    store = Store(tmp_path)
    w = store.create_workspace(fixture)
    try:
        store.set_setting(w, "dialect", dialect)
        assert Importer(store, w).files([(fixture, original)], {path.suffix}).accepted == 1
        assert analyze(store, w)["analyzed"] == 1
        graph = LineageGraph(store.assets(w), store.edges(w))
        assert {(graph.nodes[s]["name"], graph.nodes[t]["name"]) for s, t in graph.graph.edges} == expected
        assert not validate_lineage_evidence(store, w)["invalid"]
        asset = graph.search("raw.orders")[0]["asset_id"]
        assert "id" in {u["column_name"] for u in column_report(store, w, asset)}
        for edge in store.edges(w):
            assert edge["code"] in original.decode()
            assert edge["code"].splitlines() == original.decode().splitlines()[edge["start_line"] - 1:edge["end_line"]]
        assert analyze(store, w)["cached"] == 1
        assert store.original(store.files(w)[0]["file_id"]) == original
    finally:
        store.close()
    store = Store(tmp_path)
    service = AgentService(store)
    try:
        report = service.call("lineage", w, asset="mart.orders" if dialect != "snowflake" else "mart.active_orders")
        assert "raw.orders" in {row["name"] for row in report["items"]}
        assert report["analysis_current"] and report["complete"]
        assert len(store.edges(w)) == 2
    finally:
        service.close()
        store.close()


@pytest.mark.parametrize("body", ["INSERT INTO IDENTIFIER($dest) SELECT id FROM raw.a", "INSERT INTO mart.x SELECT id FROM raw.a WHERE id = ?"])
def test_literal_sql_rejects_runtime_identifiers_and_bind_parameters(body: str) -> None:
    """Verify that literal sql rejects runtime identifiers and bind parameters.

    Args:
        body: Body value used by the test case.
    """
    result = parse_sql(f"EXECUTE IMMEDIATE $${body}$$;", "snowflake")
    assert not result.operations
    assert any(d.severity != "info" for d in result.diagnostics)


def test_macro_expansion_stops_at_resource_limit() -> None:
    """Verify that macro expansion stops at resource limit."""
    result = parse_sas("data mart.x; set &source.; run;", macros={"source": "raw." + "a" * (1024 * 1024)})
    assert not result.operations
    assert result.diagnostics
