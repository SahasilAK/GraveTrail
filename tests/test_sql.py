import pytest

from dataforge.parsers.sql import parse_sql


def names(refs):
    return {r.name.lower() for r in refs}


@pytest.mark.parametrize("sql,kind,target,sources", [
    ("create table mart.x as select * from raw.a join raw.b on a.id=b.id;", "CREATE", "mart.x", {"raw.a", "raw.b"}),
    ("insert into mart.x select id from raw.a union all select id from raw.b;", "INSERT", "mart.x", {"raw.a", "raw.b"}),
    ("update mart.x set v=b.v from raw.b b where mart.x.id=b.id;", "UPDATE", "mart.x", {"raw.b"}),
    ("merge into mart.x t using raw.b b on t.id=b.id when matched then update set v=b.v;", "MERGE", "mart.x", {"raw.b"}),
    ("delete from mart.x using raw.b where mart.x.id=raw.b.id;", "DELETE", "mart.x", {"raw.b"}),
    ('create or replace view "mart"."X" as select id from "raw"."A";', "CREATE", "mart.x", {"raw.a"}),
])
def test_operations(sql, kind, target, sources):
    result = parse_sql(sql)
    assert not [d for d in result.diagnostics if d.severity == "error"]
    op = result.operations[0]
    assert op.kind == kind
    assert names(op.targets) == {target}
    assert names(op.sources) - {target} == sources
    assert op.code == sql


def test_cte_scope_and_direct_columns():
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


def test_ambiguous_columns_and_wildcard_are_not_invented():
    r = parse_sql("select id,a.*,b.value from raw.a a join raw.b b on a.id=b.id")
    op = r.operations[0]
    assert any(d.symbol == "id" for d in r.diagnostics)
    assert any(u.column == "*" and u.table == "raw.a" and u.status == "unresolved" for u in op.usages)
    assert not any(u.column == "id" and u.context == "SELECT" for u in op.usages)


def test_temporary_and_bad_statements():
    r = parse_sql("create temporary table t as select * from raw.a;\nselect from ;")
    assert r.operations[0].targets[0].temporary
    assert any(d.severity == "error" for d in r.diagnostics)


def test_semicolon_in_comment_literal_and_subquery():
    r = parse_sql("select q.id from (select id from raw.a where txt='a;b') q; -- ;\nselect id from raw.b;")
    assert len(r.operations) == 2
    assert names(r.operations[0].sources) == {"raw.a"}
    assert [(u.table, u.column) for u in r.operations[0].usages] == [("raw.a", "id"), ("raw.a", "txt")]
