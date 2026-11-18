from typing import Any

from dataforge.parsers.sql import parse_sql


def names(refs: Any) -> Any:
    """Handle names for the test scenario.

    Args:
        refs: Refs value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    return {r.name.lower() for r in refs}


def test_cte_scope_and_direct_columns() -> None:
    """Verify that cte scope and direct columns."""
    code = """-- customer summary
CREATE TABLE mart.summary AS
WITH c AS (SELECT a.id,a.name FROM raw.customers a WHERE a.active=1)
SELECT c.id,o.total FROM c JOIN raw.orders o ON c.id=o.customer_id;
SELECT id FROM mart.summary;"""
    result = parse_sql(code)
    op = result.operations[0]
    assert names(op.sources) == {"raw.customers", "raw.orders"}
    assert not any(r.name == "c" for r in op.sources)
    cols = {(u.table.lower(), u.column.lower()) for u in op.usages}
    assert cols == {("raw.customers", "id"), ("raw.customers", "name"),
                    ("raw.customers", "active"), ("raw.orders", "total"), ("raw.orders", "customer_id")}
    assert op.start == 1 and op.end == 4
    assert result.operations[1].start == 5
    assert not any(u.table == "raw.customers" for u in result.operations[1].usages)


def test_ambiguous_columns_and_wildcard_are_not_invented() -> None:
    """Verify that ambiguous columns and wildcard are not invented."""
    r = parse_sql("select id,a.*,b.value from raw.a a join raw.b b on a.id=b.id")
    op = r.operations[0]
    assert any(d.symbol == "id" for d in r.diagnostics)
    assert any(u.column == "*" and u.table == "raw.a" and u.status == "unresolved" for u in op.usages)
    assert not any(u.column == "id" and u.context == "SELECT" for u in op.usages)


def test_quoted_dotted_identifier_keeps_component_boundaries() -> None:
    """Verify that quoted dotted identifier keeps component boundaries."""
    from dataforge.models import canonical
    r = parse_sql('create table mart.x as select * from "raw.orders"; create table mart.y as select * from raw.orders;')
    a, b = [o.sources[0].name for o in r.operations]
    assert canonical(a) != canonical(b)
