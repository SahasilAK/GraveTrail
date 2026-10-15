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


def test_unused_cte_contributes_no_lineage_or_columns():
    r = parse_sql("CREATE TABLE mart.x AS WITH unused AS (SELECT secret FROM raw.secret) SELECT id FROM raw.real;")
    assert names(r.operations[0].sources) == {"raw.real"}
    assert {u.table for u in r.operations[0].usages} == {"raw.real"}


def test_quoted_dotted_identifier_keeps_component_boundaries():
    from dataforge.models import canonical
    r = parse_sql('create table mart.x as select * from "raw.orders"; create table mart.y as select * from raw.orders;')
    a, b = [o.sources[0].name for o in r.operations]
    assert canonical(a) != canonical(b)


def test_unused_cte_in_update_is_not_a_read_dependency():
    r = parse_sql('WITH unused AS (SELECT id FROM raw.secret) UPDATE mart.x SET v=b.v FROM raw.b b WHERE mart.x.id=b.id')
    assert names(r.operations[0].sources) == {"raw.b"}


def test_used_cte_in_update_resolves_base_source():
    r = parse_sql('WITH c AS (SELECT id,v FROM raw.a) UPDATE mart.x SET v=c.v FROM c WHERE mart.x.id=c.id')
    assert names(r.operations[0].sources) == {"raw.a"}
    assert not any(d.symbol == "c" for d in r.diagnostics)


def test_order_alias_is_not_fabricated_as_a_base_column():
    r = parse_sql('SELECT amount*2 AS doubled FROM raw.a ORDER BY doubled')
    assert {u.column for u in r.operations[0].usages} == {"amount"}


def test_single_target_update_reads_unqualified_rhs_columns():
    r = parse_sql('UPDATE mart.employee SET salary=salary*1.1 WHERE active=1')
    assert {u.column for u in r.operations[0].usages} == {"salary", "active"}


@pytest.mark.parametrize("name", ["#stage", "##stage"])
def test_tsql_temporary_prefix_survives_ddl_reads_and_column_attribution(name):
    code = f"CREATE TABLE {name} (id INT); SELECT id FROM {name}; SELECT id FROM stage;"
    result = parse_sql(code, "tsql")
    assert result.operations[0].targets[0].name == name
    assert result.operations[0].targets[0].temporary
    assert result.metadata["declared_schemas"][0]["table"] == name
    assert result.operations[1].sources[0].name == name
    assert result.operations[1].usages[0].table == name
    assert result.operations[2].sources[0].name == "stage"


def test_postgres_select_into_temporary_keeps_target_lifetime():
    result = parse_sql("SELECT id INTO TEMPORARY TABLE stage FROM raw.orders;", "postgres")
    operation = result.operations[0]
    assert operation.kind == "SELECT_INTO"
    assert operation.targets[0].name == "stage" and operation.targets[0].temporary
    assert names(operation.sources) == {"raw.orders"}


@pytest.mark.parametrize("dialect,into", [("tsql", "#stage"), ("postgres", "TEMPORARY TABLE stage")])
def test_select_into_set_query_records_all_branches_and_target(dialect, into):
    result = parse_sql(f"SELECT id INTO {into} FROM raw.a UNION ALL SELECT id FROM raw.b;", dialect)
    operation = result.operations[0]
    assert operation.kind == "SELECT_INTO"
    assert names(operation.sources) == {"raw.a", "raw.b"}
    assert operation.targets[0].temporary
    assert operation.targets[0].name == ("#stage" if dialect == "tsql" else "stage")


@pytest.mark.parametrize("sql", ["CREATE TABLE tempdb..##stage(id INT);",
                                 "SELECT id INTO tempdb..##stage FROM raw.a;"])
def test_qualified_global_tsql_temporary_target_and_reads(sql):
    result = parse_sql(sql + " SELECT id FROM tempdb..##stage;", "tsql")
    assert result.operations[0].targets[0].temporary
    assert result.operations[1].sources[0].temporary
    assert result.operations[0].targets[0].name == result.operations[1].sources[0].name
