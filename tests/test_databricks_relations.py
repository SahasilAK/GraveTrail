"""Check Databricks relation transforms at the SQL parser boundary."""

import pytest

from dataforge.parsers.sql import parse_sql


def operation(sql: str, *, sources: set[str], dialect: str = "databricks"):
    """Check physical table lineage independently of derivations."""
    result = parse_sql(sql, dialect)
    assert len(result.operations) == 1, result.diagnostics
    operation = result.operations[0]
    assert {source.name for source in operation.sources} == sources
    assert {target.name for target in operation.targets} == {"mart.result"}
    assert operation.code.rstrip(";") == sql.rstrip(";")
    return operation


def outputs(operation):
    """Index destination outputs while leaving intermediate facts available."""
    return {record["target_column"]: record for record in operation.derivations
            if record["target_table"] == "mart.result"}


def inputs(record, role="value"):
    """Select source dependencies for a given role."""
    return {(item["table"], item["column"]) for item in record["inputs"] if item["role"] == role}


@pytest.mark.parametrize(
    ("lateral", "names"),
    [
        ("EXPLODE(e.items) AS item", ["item"]),
        ("OUTER EXPLODE(e.items) f AS item_key, item_value", ["f.item_key", "item_value"]),
        ("POSEXPLODE(e.items) f AS item_pos, item", ["item_pos", "f.item"]),
    ],
)
def test_lateral_view_generated_columns_trace_to_the_collection(lateral, names):
    sql = f"CREATE TABLE mart.result AS SELECT e.id, {', '.join(names)} FROM raw.events e LATERAL VIEW {lateral}"
    parsed = operation(sql, sources={"raw.events"})
    records = outputs(parsed)
    assert inputs(records["id"]) == {("raw.events", "id")}
    for name in names:
        record = records[name.split(".")[-1]]
        assert record["status"] == "verified"
        assert record["expression"] == name
        assert inputs(record) == {("raw.events", "items")}
    assert {(u.table, u.column) for u in parsed.usages} == {
        ("raw.events", "id"), ("raw.events", "items"),
    }


def test_unsupported_generator_leaves_the_sibling_projection_verified():
    sql = ("CREATE TABLE mart.result AS SELECT e.id, generated FROM raw.events e "
           "LATERAL VIEW mystery(e.items) f AS generated")
    parsed = operation(sql, sources={"raw.events"})
    records = outputs(parsed)
    assert records["id"]["status"] == "verified"
    assert inputs(records["id"]) == {("raw.events", "id")}
    assert records["generated"]["status"] == "unresolved"
    assert any("generator" in reason.casefold() for reason in records["generated"]["coverage"])
    assert inputs(records["generated"]) == set()
    assert ("raw.events", "generated") not in {(u.table, u.column) for u in parsed.usages}


@pytest.mark.parametrize("lateral", ["EXPLODE(ARRAY(e.items)) f AS item, extra", "EXPLODE(e.items) f AS item, item"])
def test_invalid_generated_layout_does_not_verify_aliases(lateral):
    sql = f"CREATE TABLE mart.result AS SELECT e.id, item FROM raw.events e LATERAL VIEW {lateral}"
    records = outputs(operation(sql, sources={"raw.events"}))
    assert records["id"]["status"] == "verified"
    assert records["item"]["status"] == "unresolved"
    assert inputs(records["item"]) == set()


def test_chained_lateral_view_collection_resolves_only_preceding_outputs():
    sql = ("CREATE TABLE mart.result AS SELECT first_item, child FROM raw.events e "
           "LATERAL VIEW EXPLODE(items) first AS first_item "
           "LATERAL VIEW EXPLODE(first_item) second AS child "
           "LATERAL VIEW EXPLODE(e.other) third AS items")
    records = outputs(operation(sql, sources={"raw.events"}))
    assert records["first_item"]["status"] == records["child"]["status"] == "verified"
    assert inputs(records["first_item"]) == inputs(records["child"]) == {("raw.events", "items")}


def test_pivot_column_uses_its_own_aggregate_and_tuple_key():
    sql = (
        "CREATE TABLE mart.result AS SELECT p.store, p.east_sales, p.west_avg FROM "
        "(SELECT store, region, quarter, amount, discount FROM raw.sales) s "
        "PIVOT (SUM(amount) AS sales, AVG(discount) AS avg FOR (region, quarter) "
        "IN (('east', 1) AS east, ('west', 2) AS west)) AS p"
    )
    parsed = operation(sql, sources={"raw.sales"})
    records = outputs(parsed)
    assert records["store"]["status"] == "verified"
    assert inputs(records["store"]) == {("s", "store")}
    for name, column in [("east_sales", "amount"), ("west_avg", "discount")]:
        assert records[name]["status"] == "verified"
        assert records[name]["expression"] == f"p.{name}"
        assert inputs(records[name]) == {("s", column)}
        assert inputs(records[name], "value_selection") == {
            ("s", "region"), ("s", "quarter"), ("s", "store"),
        }
    assert {(u.table, u.column) for u in parsed.usages} == {
        ("raw.sales", "store"), ("raw.sales", "region"), ("raw.sales", "quarter"),
        ("raw.sales", "amount"), ("raw.sales", "discount"),
    }


def test_nonliteral_pivot_preserves_table_edges_and_grouping_column():
    sql = (
        "CREATE TABLE mart.result AS SELECT store, east FROM "
        "(SELECT store, region, amount FROM raw.sales) s "
        "PIVOT (SUM(amount) FOR region IN (:region AS east))"
    )
    records = outputs(operation(sql, sources={"raw.sales"}))
    assert records["store"]["status"] == "verified"
    assert inputs(records["store"]) == {("s", "store")}
    assert records["east"]["status"] == "unresolved"
    assert any("pivot" in reason.casefold() for reason in records["east"]["coverage"])
    assert ("s", "east") not in inputs(records["east"])


@pytest.mark.parametrize(("prefix", "suffix"), [("", ""), ("p.", " AS p"), ("raw.sales.", "")])
def test_pivot_does_not_publish_consumed_columns_as_grouping_columns(prefix, suffix):
    sql = (f"CREATE TABLE mart.result AS SELECT {prefix}store, {prefix}amount, {prefix}east "
           f"FROM raw.sales PIVOT (SUM(amount) FOR region IN ('east')){suffix}")
    parsed = operation(sql, sources={"raw.sales"})
    records = outputs(parsed)
    assert inputs(records["store"]) == {("raw.sales", "store")}
    assert records["amount"]["status"] == "unresolved"
    assert inputs(records["amount"]) == set()
    assert inputs(records["east"]) == {("raw.sales", "amount")}
    assert inputs(records["east"], "value_selection") >= {("raw.sales", "region")}
    assert {(u.table, u.column) for u in parsed.usages} == {
        ("raw.sales", "store"), ("raw.sales", "amount"), ("raw.sales", "region"),
    }


def test_pivot_output_collision_keeps_both_candidates_unresolved():
    sql = (
        "CREATE TABLE mart.result AS SELECT store, east FROM "
        "(SELECT store, east, region, amount FROM raw.sales) s "
        "PIVOT (SUM(amount) FOR region IN ('east'))"
    )
    records = outputs(operation(sql, sources={"raw.sales"}))
    assert records["store"]["status"] == "verified"
    assert records["east"]["status"] == "unresolved"
    assert inputs(records["east"]) == set()


def test_pivot_over_a_join_retains_reads_without_guessing_joined_outputs():
    sql = (
        "CREATE TABLE mart.result AS SELECT a.amount, east FROM "
        "(raw.sales a JOIN raw.markets b ON a.id = b.id) "
        "PIVOT (SUM(a.amount) FOR b.region IN ('east'))"
    )
    records = outputs(operation(sql, sources={"raw.sales", "raw.markets"}))
    assert {record["status"] for record in records.values()} == {"unresolved"}
    assert all(not inputs(record) for record in records.values())


def test_pivot_star_composes_with_a_generator_and_aggregate():
    sql = (
        "CREATE TABLE mart.result AS "
        "WITH totals AS (SELECT e.store, item, SUM(e.amount) AS total FROM raw.sales e "
        "LATERAL VIEW EXPLODE(e.items) f AS item GROUP BY e.store, item) "
        "SELECT p.* FROM totals PIVOT (SUM(total) FOR item IN ('x', 'y' AS why)) AS p"
    )
    parsed = operation(sql, sources={"raw.sales"})
    final = [record for record in parsed.derivations if record["target_table"] == "mart.result"]
    assert [record["target_column"] for record in final] == ["store", "x", "why"]
    intermediate = {record["target_column"]: record for record in parsed.derivations
                    if record["target_table"] == "totals"}
    assert inputs(intermediate["item"]) == {("raw.sales", "items")}
    assert inputs(intermediate["total"]) == {("raw.sales", "amount")}
    assert {record["status"] for record in final} == {"verified"}
    assert inputs(final[0]) == {("totals", "store")}
    for record in final[1:]:
        assert record["expression"] == "p.*"
        assert inputs(record) == {("totals", "total")}
        assert inputs(record, "value_selection") == {("totals", "item"), ("totals", "store")}
