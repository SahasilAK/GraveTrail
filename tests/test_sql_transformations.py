"""Transformation facts stay separate from direct column usage."""
from typing import Any

from dataforge.parsers.sql import parse_sql


def derivations(sql: str, dialect: str="") -> Any:
    """Handle derivations for the test scenario.

    Args:
        sql: SQL source text for the test case.
        dialect: Dialect selected for the test case.

    Returns:
        Value produced for the test scenario.
    """
    result = parse_sql(sql, dialect)
    assert result.operations, result.diagnostics
    return result.operations[-1].derivations


def inputs(record: Any, role: Any="value") -> Any:
    """Handle inputs for the test scenario.

    Args:
        record: Record value used by the test case.
        role: Role value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    return {(item["table"], item["column"]) for item in record["inputs"] if item["role"] == role}


def databricks_query(query):
    parsed = parse_sql("CREATE TABLE dst AS " + query, "databricks")
    assert parsed.operations, parsed.diagnostics
    return parsed.operations[-1]


def test_databricks_window_qualify_and_aggregate_roles():
    op = databricks_query("""WITH q AS (SELECT id, amount, account, ts FROM src)
        SELECT id, SUM(amount) OVER (PARTITION BY account ORDER BY ts) AS running,
        ROW_NUMBER() OVER (PARTITION BY account ORDER BY ts) AS rn
        FROM q QUALIFY rn = 1""")
    assert {s.name for s in op.sources} == {"src"}
    records = {r["target_column"]: r for r in op.derivations if not r["scope"]}
    assert inputs(records["running"]) == {("q", "amount")}
    assert inputs(records["running"], "partition") == {("q", "account")}
    assert inputs(records["running"], "order") == {("q", "ts")}
    assert inputs(records["id"], "row_filter") == {("q", "account"), ("q", "ts")}
    assert inputs(records["id"]) == {("q", "id")}


def test_expression_and_context_are_separate() -> None:
    """Verify that expression and context are separate."""
    records = derivations("""CREATE TABLE mart.t AS SELECT
      o.id, o.qty  * /* preserve */ o.price AS gross,
      COALESCE(d.discount, 0) AS discount, 42 AS constant
      FROM raw.orders o LEFT JOIN raw.discounts d ON o.id = d.id WHERE o.status = 'C';""")
    gross = next(r for r in records if r["target_column"] == "gross")
    assert inputs(gross) == {("raw.orders", "qty"), ("raw.orders", "price")}
    assert gross["expression"] == "o.qty  * /* preserve */ o.price AS gross"
    assert inputs(gross, "join") == {("raw.orders", "id"), ("raw.discounts", "id")}
    assert inputs(gross, "row_filter") == {("raw.orders", "status")}
    constant = next(r for r in records if r["target_column"] == "constant")
    assert inputs(constant) == set()
    assert constant["status"] == "verified"
    assert constant["category"] == "constant"


def test_case_window_and_count_roles() -> None:
    """Verify that case window and count roles."""
    records = derivations("""CREATE VIEW v AS SELECT
      CASE WHEN flag = 1 THEN amount ELSE fallback END AS chosen,
      SUM(amount) OVER (PARTITION BY account ORDER BY ts) AS running,
      COUNT(*) AS n FROM source""")
    chosen, running, count = records
    assert inputs(chosen) == {("source", "amount"), ("source", "fallback")}
    assert inputs(chosen, "value_selection") == {("source", "flag")}
    assert inputs(running) == {("source", "amount")}
    assert inputs(running, "partition") == {("source", "account")}
    assert inputs(running, "order") == {("source", "ts")}
    assert inputs(count) == set()
    assert inputs(count, "rowset") == {("source", "")}


def test_unknown_function_has_coverage() -> None:
    record = derivations("CREATE TABLE dst AS SELECT mystery(a) AS b FROM src")[0]
    assert record["status"] == "unresolved"
    assert any("function" in item.lower() for item in record["coverage"])


def test_scalar_correlated_subquery_retains_scoped_value_and_predicates():
    dialect = 'postgres'
    projection = "SELECT (SELECT MAX(b.value) FROM b WHERE b.id = a.id) AS v"
    sql = projection + " INTO dst FROM a" if dialect == "tsql" else "CREATE TABLE dst AS " + projection + " FROM a"
    inner, outer = derivations(sql, dialect)
    assert outer["target_column"] == "v"
    assert outer["inputs"][0]["scope"] == inner["scope"]
    assert inputs(inner) == {("b", "value")}
    assert inputs(inner, "row_filter") == {("b", "id"), ("a", "id")}
    assert inner["status"] == outer["status"] == "verified"
