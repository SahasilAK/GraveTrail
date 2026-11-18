"""Check Databricks relation transforms at the SQL parser boundary."""


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


def test_lateral_view_generated_columns_trace_to_the_collection():
    lateral, names = ('OUTER EXPLODE(e.items) f AS item_key, item_value', ['f.item_key', 'item_value'])
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


def test_pivot_over_a_join_retains_reads_without_guessing_joined_outputs():
    sql = (
        "CREATE TABLE mart.result AS SELECT a.amount, east FROM "
        "(raw.sales a JOIN raw.markets b ON a.id = b.id) "
        "PIVOT (SUM(a.amount) FOR b.region IN ('east'))"
    )
    records = outputs(operation(sql, sources={"raw.sales", "raw.markets"}))
    assert {record["status"] for record in records.values()} == {"unresolved"}
    assert all(not inputs(record) for record in records.values())
