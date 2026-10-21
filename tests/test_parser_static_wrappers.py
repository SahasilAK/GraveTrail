import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from dataforge.models import ParseResult, statements
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


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_postgres_sql_procedure_body_has_original_definition_evidence(newline: str) -> None:
    """Verify that postgres sql procedure body has original definition evidence.

    Args:
        newline: Newline value used by the test case.
    """
    content = (FIXTURES / "postgres_procedure.sql").read_text().replace("\n", newline)
    result = parse_sql(content, "postgres")
    assert pairs(result) == {("raw.orders", "mart.orders"), ("mart.orders", "mart.order_audit")}
    assert len(result.operations) == 2
    assert all(op.code == content.strip() and (op.start, op.end) == (1, 9)
               and op.method == "sql-procedure-body" for op in result.operations)
    assert {(u.table, u.column) for op in result.operations for u in op.usages} == {
        ("raw.orders", "id"), ("raw.orders", "amount"), ("raw.orders", "active"), ("mart.orders", "id")}
    assert any("invocation" in d.message.lower() and d.severity == "info" for d in result.diagnostics)
    assert ParseResult.from_dict(result.to_dict()) == result


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_snowflake_literal_sql_retains_outer_quotes_and_exact_lines(newline: str) -> None:
    """Verify that snowflake literal sql retains outer quotes and exact lines.

    Args:
        newline: Newline value used by the test case.
    """
    content = (FIXTURES / "snowflake_literal.sql").read_text().replace("\n", newline)
    result = parse_sql(content, "snowflake")
    assert pairs(result) == {("raw.orders", "mart.active_orders"), ("raw.orders", "mart.order_totals")}
    assert [op.code for op in result.operations] == [code for code, _, _ in statements(content)]
    assert [(op.start, op.end) for op in result.operations] == [(1, 3), (4, 5)]
    assert all(op.method == "sql-literal" for op in result.operations)
    assert {u.column for op in result.operations for u in op.usages} == {"id", "state", "customer_id", "amount"}


@pytest.mark.parametrize("body", [
    "BEGIN IF false THEN INSERT INTO mart.fake SELECT id FROM raw.fake; END IF; END",
    "SELECT 1; IF false THEN SELECT id FROM raw.fake; END IF;",
    "EXECUTE 'INSERT INTO mart.fake SELECT id FROM raw.fake';",
])
def test_procedure_control_flow_never_leaks_edges(body: str) -> None:
    """Verify that procedure control flow never leaks edges.

    Args:
        body: Body value used by the test case.
    """
    content = f"CREATE PROCEDURE mart.p() LANGUAGE SQL AS $$ {body} $$; SELECT id FROM raw.real;"
    result = parse_sql(content, "postgres")
    assert pairs(result) == set()
    assert {s.name for op in result.operations for s in op.sources} == {"raw.real"}
    assert any(d.severity != "info" for d in result.diagnostics)


@pytest.mark.parametrize("header", ["LANGUAGE plpgsql", "LANGUAGE SQL SET search_path TO other", "LANGUAGE python"])
def test_non_sql_or_context_changing_procedures_are_unresolved(header: str) -> None:
    """Verify that non sql or context changing procedures are unresolved.

    Args:
        header: Header value used by the test case.
    """
    result = parse_sql(f"CREATE PROCEDURE mart.p() {header} AS $$ INSERT INTO mart.x SELECT id FROM raw.a; $$;", "postgres")
    assert not result.operations
    assert any(d.severity == "warning" for d in result.diagnostics)


@pytest.mark.parametrize("expression", [
    "query_text", "$query_text", "'INSERT INTO mart.x SELECT id FROM ' || source_name",
    "'INSERT INTO mart.x SELECT id FROM IDENTIFIER(?)' USING (source_name)",
    "'INSERT INTO mart.x SELECT id FROM raw.a; INSERT INTO mart.y SELECT id FROM raw.b;'",
    "$$BEGIN IF (false) THEN INSERT INTO mart.fake SELECT id FROM raw.fake; END IF; END;$$",
])
def test_runtime_dynamic_sql_is_unresolved(expression: str) -> None:
    """Verify that runtime dynamic sql is unresolved.

    Args:
        expression: Expression value used by the test case.
    """
    result = parse_sql(f"EXECUTE IMMEDIATE {expression};", "snowflake")
    assert not result.operations
    assert result.diagnostics


def test_nested_literal_sql_has_a_bounded_depth() -> None:
    """Verify that nested literal sql has a bounded depth."""
    code = "INSERT INTO mart.x SELECT id FROM raw.a"
    for _ in range(10):
        code = "EXECUTE IMMEDIATE '" + code.replace("'", "''") + "'"
    result = parse_sql(code, "snowflake")
    assert not result.operations
    assert any("limit" in d.message.lower() for d in result.diagnostics)


def test_procedure_ddl_is_not_an_unconditional_declared_schema() -> None:
    """Verify that procedure ddl is not an unconditional declared schema."""
    result = parse_sql("CREATE PROCEDURE mart.p() LANGUAGE SQL AS $$ CREATE TABLE mart.x (id INT); $$;", "postgres")
    assert [t.name for op in result.operations for t in op.targets] == ["mart.x"]
    assert not result.metadata.get("declared_schemas")


def test_sas_chained_let_and_double_quoted_paths_preserve_original_blocks() -> None:
    """Verify that sas chained let and double quoted paths preserve original blocks."""
    code = (FIXTURES / "sas_macro_variables.sas").read_text()
    result = parse_sas(code)
    assert pairs(result) == {("raw.orders", "mart.orders"), ("file:input/orders.csv", "work.imported")}
    assert not result.diagnostics
    assert {u.column for op in result.operations for u in op.usages} == {"id", "amount"}
    assert result.operations[0].code == "data &target.;\n  set &source.;\n  keep id amount;\nrun;"
    assert (result.operations[0].start, result.operations[0].end) == (5, 8)


def test_sas_single_quoted_macro_path_is_literal() -> None:
    """Verify that sas single quoted macro path is literal."""
    code = "%let folder=input; proc import datafile='&folder./orders.csv' out=work.x; run;"
    assert pairs(parse_sas(code)) == {("file:&folder./orders.csv", "work.x")}


@pytest.mark.parametrize("assignment", ["%sysget(SOURCE)", "&missing.", "&&prefix&i."])
def test_unresolved_let_reassignment_invalidates_previous_value(assignment: str) -> None:
    """Verify that unresolved let reassignment invalidates previous value.

    Args:
        assignment: Assignment value used by the test case.
    """
    result = parse_sas(f"%let source=raw.orders; %let source={assignment}; data mart.x; set &source.; run;")
    assert not pairs(result)
    assert result.diagnostics


def test_let_captures_known_value_at_assignment_time() -> None:
    """Verify that let captures known value at assignment time."""
    result = parse_sas("%let lib=raw; %let source=&lib..orders; %let lib=other; data mart.x; set &source.; run;")
    assert pairs(result) == {("raw.orders", "mart.x")}


@pytest.mark.parametrize("control", [
    "%if &runtime %then %do; %let source=raw.other; %end;",
    "%unknown();",
    "data _null_; call symputx('source', 'raw.other'); run;",
])
def test_unknown_macro_mutation_cannot_reuse_known_values(control: str) -> None:
    """Verify that unknown macro mutation cannot reuse known values.

    Args:
        control: Control value used by the test case.
    """
    result = parse_sas(f"%let source=raw.orders; {control} data mart.x; set &source.; run;")
    assert not pairs(result)
    assert result.diagnostics


def test_configured_macro_cannot_inject_unparsed_statements() -> None:
    """Verify that configured macro cannot inject unparsed statements."""
    result = parse_sas("data mart.x; set &source.; run;", macros={"source": "raw.a; set raw.fake;"})
    assert not pairs(result)
    assert result.diagnostics


def test_single_quoted_unknown_reference_and_apostrophe_in_double_quotes() -> None:
    """Verify that single quoted unknown reference and apostrophe in double quotes."""
    result = parse_sas('''%let folder=input;
proc import datafile='&unknown./orders.csv' out=work.literal; run;
proc import datafile="O'Neil/&folder./orders.csv" out=work.expanded; run;''')
    assert pairs(result) == {("file:&unknown./orders.csv", "work.literal"),
                             ("file:O'Neil/input/orders.csv", "work.expanded")}
    assert not result.diagnostics


def test_unknown_dialect_stays_a_controlled_parser_diagnostic() -> None:
    """Verify that unknown dialect stays a controlled parser diagnostic."""
    result = parse_sql("SELECT id FROM raw.a;", "missing_dialect")
    assert not result.operations
    assert any(d.severity == "error" for d in result.diagnostics)


@pytest.mark.parametrize("fixture,dialect,expected", [
    ("postgres_procedure.sql", "postgres", {("raw.orders", "mart.orders"), ("mart.orders", "mart.order_audit")}),
    ("snowflake_literal.sql", "snowflake", {("raw.orders", "mart.active_orders"), ("raw.orders", "mart.order_totals")}),
    ("sas_macro_variables.sas", "", {("raw.orders", "mart.orders"), ("file:input/orders.csv", "work.imported")}),
])
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["LF", "CRLF"])
def test_static_wrapper_persistence_cache_and_evidence(tmp_path: Path, fixture: str, dialect: str, expected: Any, newline: Any) -> None:
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


def test_evidence_validation_rejects_newline_normalized_statement(tmp_path: Path) -> None:
    """Verify that evidence validation rejects newline normalized statement.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.ingestion import Importer
    from dataforge.reporting import validate_lineage_evidence
    from dataforge.services import analyze
    from dataforge.store import Store

    store = Store(tmp_path)
    try:
        w = store.create_workspace("Exact evidence")
        Importer(store, w).files([("q.sql", b"INSERT INTO mart.x\r\nSELECT id FROM raw.a;\r\n")], {".sql"})
        analyze(store, w)
        assert not validate_lineage_evidence(store, w)["invalid"]
        store.execute("UPDATE statements SET code=? WHERE workspace_id=?", ["INSERT INTO mart.x\nSELECT id FROM raw.a;", w])
        assert len(validate_lineage_evidence(store, w)["invalid"]) == 1
    finally:
        store.close()


@pytest.mark.parametrize("body", [
    "INSERT INTO IDENTIFIER($dest) SELECT id FROM raw.a",
    "INSERT INTO IDENTIFIER(?) SELECT id FROM raw.a",
    "INSERT INTO mart.x SELECT id FROM IDENTIFIER($source)",
    "INSERT INTO mart.x SELECT id FROM raw.a WHERE id = ?",
])
def test_literal_sql_rejects_runtime_identifiers_and_bind_parameters(body: str) -> None:
    """Verify that literal sql rejects runtime identifiers and bind parameters.

    Args:
        body: Body value used by the test case.
    """
    result = parse_sql(f"EXECUTE IMMEDIATE $${body}$$;", "snowflake")
    assert not result.operations
    assert any(d.severity != "info" for d in result.diagnostics)


def test_macro_invocation_inside_let_invalidates_other_variables() -> None:
    """Verify that macro invocation inside let invalidates other variables."""
    code = """%let source=raw.old;
%macro change();
  %global source;
  %let source=raw.new;
%mend;
%let unused=%change();
data mart.x; set &source.; run;"""
    assert not pairs(parse_sas(code))


def test_conditional_symput_invalidates_values_but_quoted_calls_do_not() -> None:
    """Verify that conditional symput invalidates values but quoted calls do not."""
    prefix = "%let source=raw.old; data _null_; "
    suffix = " run; data mart.x; set &source.; run;"
    assert not pairs(parse_sas(prefix + "if 1 then call symputx('source','raw.new');" + suffix))
    result = parse_sas(prefix + '''text="call symputx('source','raw.new')";''' + suffix)
    assert pairs(result) == {("raw.old", "mart.x")}


def test_configured_macro_call_inside_let_invalidates_other_values() -> None:
    """Verify that configured macro call inside let invalidates other values."""
    result = parse_sas("%let unused=&unknown.; data mart.x; set &source.; run;",
                       macros={"source": "raw.old", "unknown": "%change()"})
    assert not pairs(result)


@pytest.mark.parametrize("dialect,code", [
    ("tsql", "CREATE PROCEDURE mart.p AS BEGIN SELECT 1; IF 0=1 BEGIN INSERT INTO mart.x SELECT id FROM raw.fake; END; END;"),
    ("postgres", "CREATE PROCEDURE mart.p() LANGUAGE SQL BEGIN ATOMIC SELECT 1; INSERT INTO mart.x SELECT id FROM raw.fake; END;"),
])
def test_unsupported_procedure_format_never_reinterprets_body_tail_as_top_level(dialect: str, code: str) -> None:
    """Verify that unsupported procedure format never reinterprets body tail as top level.

    Args:
        dialect: Dialect selected for the test case.
        code: Code value used by the test case.
    """
    result = parse_sql(code, dialect)
    assert not result.operations
    assert any("remainder" in d.message.lower() for d in result.diagnostics)


def test_macro_expansion_stops_at_resource_limit() -> None:
    """Verify that macro expansion stops at resource limit."""
    result = parse_sas("data mart.x; set &source.; run;", macros={"source": "raw." + "a" * (1024 * 1024)})
    assert not result.operations
    assert result.diagnostics


def test_procedure_parameters_remain_unresolved() -> None:
    """Verify that procedure parameters remain unresolved."""
    result = parse_sql("CREATE PROCEDURE mart.p(source_name text) LANGUAGE SQL AS $$INSERT INTO mart.x SELECT id FROM raw.a;$$;", "postgres")
    assert not result.operations
    assert result.diagnostics


def test_commented_sql_with_long_whitespace_finishes_without_backtracking() -> None:
    # A subprocess deadline also protects the test runner if exponential scanning returns.
    """Verify that commented sql with long whitespace finishes without backtracking."""
    script = """
from dataforge.parsers.sql import parse_sql
code = '/* CREATE PROCEDURE is only comment text */\\n' + ' ' * 100_000 + 'CREATE TABLE mart.x AS SELECT id FROM raw.a;'
result = parse_sql(code)
assert not result.diagnostics
assert len(result.operations) == 1
operation = result.operations[0]
assert operation.code == code
assert [source.name for source in operation.sources] == ['raw.a']
assert [target.name for target in operation.targets] == ['mart.x']
"""
    subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                   capture_output=True, check=True, timeout=10)


@pytest.mark.parametrize("header", ["CREATE PROCEDURE", "CREATE PROC", "CREATE OR ALTER PROC",
                                   "CREATE OR REPLACE FUNCTION", "ALTER PROCEDURE", "ALTER FUNCTION"])
def test_commented_routine_headers_preserve_unsupported_body_guard(header: str) -> None:
    """Verify that commented routine headers preserve unsupported body guard.

    Args:
        header: Header value used by the test case.
    """
    prefix = "-- misleading CREATE TABLE text\r\n\t/* first */  /* second */\n  "
    result = parse_sql(prefix + header + " mart.p AS BEGIN SELECT 1; INSERT INTO mart.x SELECT id FROM raw.fake; END;", "tsql")
    assert not result.operations
    assert any("remainder" in diagnostic.message.lower() for diagnostic in result.diagnostics)


@pytest.mark.parametrize("dialect,prefix", [("tsql", "/* outer /* inner */ rest */ "),
                                            ("snowflake", "/* outer /* inner */ ")])
def test_dialect_comment_nesting_preserves_procedure_body_guard(dialect: str, prefix: str) -> None:
    """Verify that dialect comment nesting preserves procedure body guard.

    Args:
        dialect: Dialect selected for the test case.
        prefix: Prefix value used by the test case.
    """
    code = prefix + "CREATE PROCEDURE mart.p AS BEGIN SELECT 1; INSERT INTO mart.x SELECT id FROM raw.fake; END;"
    result = parse_sql(code, dialect)
    assert not result.operations
    assert any("remainder" in diagnostic.message.lower() for diagnostic in result.diagnostics)
