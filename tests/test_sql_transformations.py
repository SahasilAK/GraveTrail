"""Transformation facts stay separate from direct column usage."""
from typing import Any

import pytest

from dataforge.parsers.sql import parse_sql


@pytest.mark.parametrize('dialect', ['', 'postgres', 'duckdb', 'snowflake', 'bigquery'])
def test_group_by_ordinal_preserves_selection_dependencies(dialect):
    records = derivations('CREATE TABLE dst AS SELECT a AS "Key", SUM(b) AS s FROM src GROUP BY 1', dialect)
    assert inputs(records[1], 'value_selection') == {('src', 'a')}
    assert records[0]['expression'] == 'a AS "Key"'


@pytest.mark.parametrize('position', ['(1)', '((1))'])
def test_parenthesized_group_ordinal_preserves_dependencies(position):
    records = derivations(f'CREATE TABLE dst AS SELECT a,SUM(b) AS s FROM src GROUP BY {position}', 'duckdb')
    assert inputs(records[1], 'value_selection') == {('src', 'a')}


@pytest.mark.parametrize('position', ['+1', '+ /* exact source */ 1', '(+1)'])
def test_unary_plus_grouping_does_not_invent_ordinal_dependencies(position):
    record = derivations(f'CREATE TABLE dst AS SELECT SUM(b) AS s FROM src GROUP BY {position}', 'duckdb')[0]
    assert inputs(record, 'value_selection') == set()
    assert record['status'] == 'unresolved' and record['coverage']


def test_query_level_sampling_has_coverage():
    record = derivations('CREATE TABLE dst AS SELECT a FROM src USING SAMPLE 1 ROWS', 'duckdb')[0]
    assert record['status'] == 'unresolved' and record['coverage']


@pytest.mark.parametrize('group', ['0', '3', '-1'])
def test_invalid_group_ordinal_has_coverage(group):
    records = derivations(f'CREATE TABLE dst AS SELECT a, SUM(b) AS s FROM src GROUP BY {group}')
    assert all(r['status'] == 'unresolved' and r['coverage'] for r in records)


def test_unqualified_group_ordinal_dialect_has_coverage():
    records = derivations('CREATE TABLE dst AS SELECT a, SUM(b) AS s FROM src GROUP BY 1', 'tsql')
    assert all(r['status'] == 'unresolved' for r in records)


def test_distinct_preserves_cross_column_selection():
    records = derivations('CREATE TABLE dst AS SELECT DISTINCT a, b FROM src')
    assert inputs(records[0], 'value_selection') == {('src', 'a'), ('src', 'b')}


def test_distinct_on_preserves_selector_or_reports_boundary():
    record = derivations('CREATE TABLE dst AS SELECT DISTINCT ON (b) a FROM src', 'postgres')[0]
    assert inputs(record, 'value_selection') == {('src', 'b')}
    assert record['status'] == 'unresolved' and record['coverage']


@pytest.mark.parametrize('modifier', ['LIMIT 10', 'OFFSET 2', 'TABLESAMPLE BERNOULLI (10)',
                                     'ORDER BY b LIMIT 10 OFFSET 2'])
def test_row_modifiers_never_silently_verify(modifier):
    record = derivations(f'CREATE TABLE dst AS SELECT a FROM src {modifier}')[0]
    assert record['status'] == 'unresolved' and record['coverage']
    assert inputs(record) == {('src', 'a')}


def test_union_duplicate_selection_has_explicit_boundary():
    records = derivations('CREATE TABLE dst AS SELECT a FROM src UNION SELECT b FROM other')
    assert all(r['status'] == 'unresolved' and r['coverage'] for r in records)
    assert [r['branch'] for r in records] == [0, 1]
    assert all(r['status'] == 'verified' for r in derivations(
        'CREATE TABLE dst AS SELECT a FROM src UNION ALL SELECT b FROM other'))


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


def test_cte_and_subquery_preserve_transformation_steps() -> None:
    """Verify that cte and subquery preserve transformation steps."""
    records = derivations("""CREATE TABLE out AS WITH x AS (SELECT a + b AS total FROM src)
      SELECT s.total * 2 AS final FROM (SELECT total FROM x) s""")
    final = next(r for r in records if r["target_table"] == "out")
    assert final["target_column"] == "final"
    assert final["inputs"][0]["scope"]
    intermediate = next(r for r in records if r["scope"] == final["inputs"][0]["scope"])
    cte = next(r for r in records if r["scope"] == intermediate["inputs"][0]["scope"])
    assert inputs(cte) == {("src", "a"), ("src", "b")}
    assert cte["expression"] == "a + b AS total"
    assert len({r["scope"] for r in records if r["scope"]}) == 2


def test_insert_maps_explicit_columns_by_position() -> None:
    """Verify that insert maps explicit columns by position."""
    records = derivations("INSERT INTO dst (first, second) SELECT a + 1 AS ignored, b FROM src")
    assert [r["target_column"] for r in records] == ["first", "second"]
    assert inputs(records[0]) == {("src", "a")}


def test_insert_without_column_list_is_unresolved() -> None:
    """Verify that insert without column list is unresolved."""
    records = derivations("INSERT INTO dst SELECT a FROM src")
    assert records[0]["target_column"] == "*"
    assert records[0]["status"] == "unresolved"
    assert records[0]["coverage"]


def test_union_maps_branches_by_position_not_alias() -> None:
    """Verify that union maps branches by position not alias."""
    records = derivations("CREATE TABLE dst AS SELECT a AS value FROM left_src UNION ALL SELECT b AS other FROM right_src")
    assert [(r["target_column"], r["branch"]) for r in records] == [("value", 0), ("value", 1)]
    assert inputs(records[0]) == {("left_src", "a")}
    assert inputs(records[1]) == {("right_src", "b")}
    assert records[1]["expression"] == "b AS other"


def test_ambiguous_unqualified_column_is_not_guessed() -> None:
    """Verify that ambiguous unqualified column is not guessed."""
    record = derivations("CREATE TABLE dst AS SELECT id FROM a JOIN b ON a.id = b.id")[0]
    assert record["status"] == "unresolved"
    assert inputs(record) == set()
    assert any("ambiguous" in item.lower() for item in record["coverage"])


def test_wildcard_retains_expansion_hook_without_guessing_schema() -> None:
    """Verify that wildcard retains expansion hook without guessing schema."""
    record = derivations("CREATE TABLE dst AS SELECT s.* FROM src s")[0]
    assert record["target_column"] == "*"
    assert record["status"] == "unresolved"
    assert record["wildcard_safe"] is True
    assert inputs(record) == {("src", "*")}


def test_unknown_function_and_unsupported_writes_have_coverage() -> None:
    """Verify that unknown function and unsupported writes have coverage."""
    record = derivations("CREATE TABLE dst AS SELECT mystery(a) AS b FROM src")[0]
    assert record["status"] == "unresolved"
    assert any("function" in item.lower() for item in record["coverage"])
    record = derivations("UPDATE dst SET a = src.b FROM src WHERE dst.id = src.id")[0]
    assert record["target_column"] == "*"
    assert record["status"] == "unresolved"
    assert inputs(record) == set()


def test_quoted_column_identity_and_exact_expression() -> None:
    """Verify that quoted column identity and exact expression."""
    record = derivations('CREATE TABLE "Dst" AS SELECT CAST("Odd Name" AS INTEGER) AS "Result" FROM "Src"', "postgres")[0]
    assert record["target_column"] == '"Result"'
    assert inputs(record) == {('Src', '"Odd Name"')}
    assert record["expression"] == 'CAST("Odd Name" AS INTEGER) AS "Result"'


def test_recursive_and_union_mismatch_are_coverage_boundaries() -> None:
    """Verify that recursive and union mismatch are coverage boundaries."""
    records = derivations("CREATE TABLE dst AS WITH RECURSIVE x AS (SELECT a FROM src UNION ALL SELECT a FROM x) SELECT a FROM x")
    assert records[0]["status"] == "unresolved"
    assert any("recursive" in c.lower() for c in records[0]["coverage"])
    records = derivations("CREATE TABLE dst AS SELECT a, b FROM src UNION ALL SELECT c FROM other")
    assert all(r["status"] == "unresolved" for r in records)
    assert all(r["coverage"] for r in records)


def test_union_cte_branches_share_intermediate_output_identity() -> None:
    """Verify that union cte branches share intermediate output identity."""
    records = derivations("CREATE TABLE dst AS WITH x(z) AS (SELECT a FROM src UNION ALL SELECT b FROM other) SELECT z FROM x")
    intermediate = [r for r in records if r["scope"]]
    assert len(intermediate) == 2
    assert {(r["target_table"], r["scope"], r["target_column"]) for r in intermediate} == {
        ("x", intermediate[0]["scope"], "z")}
    assert {r["branch"] for r in intermediate} == {0, 1}
    assert records[-1]["status"] == "verified"


def test_insert_values_and_insert_mapping_hook() -> None:
    """Verify that insert values and insert mapping hook."""
    record = derivations("INSERT INTO dst VALUES (1, 2)")[0]
    assert record["status"] == "unresolved"
    assert record["coverage"]
    record = derivations("INSERT INTO dst SELECT a FROM src")[0]
    assert record["target_mapping_missing"] is True
    assert record["ordinal"] == 0


def test_scalar_correlated_subquery_is_an_explicit_boundary() -> None:
    """Verify that scalar correlated subquery is an explicit boundary."""
    records = derivations("CREATE TABLE dst AS SELECT (SELECT MAX(b.value) FROM b WHERE b.id = a.id) AS v FROM a")
    record = next(r for r in records if r["target_table"] == "dst")
    assert record["status"] == "unresolved"
    assert any("subquery" in c.lower() for c in record["coverage"])
    assert inputs(record) == set()


def test_row_number_is_rowset_dependent_and_runtime_function_is_not_constant() -> None:
    """Verify that row number is rowset dependent and runtime function is not constant."""
    records = derivations("CREATE TABLE dst AS SELECT ROW_NUMBER() OVER () AS n, CURRENT_TIMESTAMP AS ts FROM src")
    assert records[0]["category"] == "window"
    assert records[0]["status"] == "verified"
    assert inputs(records[0], "rowset") == {("src", "")}
    assert records[1]["category"] != "constant"


def test_if_and_aggregate_filter_conditions_select_values() -> None:
    """Verify that if and aggregate filter conditions select values."""
    records = derivations("CREATE TABLE dst AS SELECT IF(flag, amount, other) AS v, SUM(amount) FILTER (WHERE flag) AS n FROM src")
    assert inputs(records[0], "value_selection") == {("src", "flag")}
    assert inputs(records[0]) == {("src", "amount"), ("src", "other")}
    assert inputs(records[1], "value_selection") == {("src", "flag")}
    assert inputs(records[1]) == {("src", "amount")}


def test_select_modifiers_are_not_part_of_original_projection() -> None:
    """Verify that select modifiers are not part of original projection."""
    record = derivations("CREATE TABLE dst AS SELECT DISTINCT ON (a) a + 1 AS b FROM src", "postgres")[0]
    assert record["expression"] == "a + 1 AS b"
    record = derivations("SELECT TOP (10) PERCENT WITH TIES CAST(a AS int) AS x INTO dst FROM src", "tsql")[0]
    assert record["expression"] == "CAST(a AS int) AS x"


def test_join_without_column_predicate_retains_relation_context() -> None:
    """Verify that join without column predicate retains relation context."""
    record = derivations("CREATE TABLE dst AS SELECT a.id FROM a JOIN b ON 1 = 1")[0]
    assert inputs(record) == {("a", "id")}
    assert inputs(record, "rowset") == {("a", ""), ("b", "")}


def test_wildcard_with_explicit_target_list_cannot_expand_by_source_names() -> None:
    """Verify that wildcard with explicit target list cannot expand by source names."""
    record = derivations("INSERT INTO dst (x, y) SELECT * FROM src")[0]
    assert record["wildcard_safe"] is False
    assert record["target_column"] == "*"
    assert record["status"] == "unresolved"


def test_quoted_alias_case_does_not_collapse_two_sources() -> None:
    """Verify that quoted alias case does not collapse two sources."""
    records = derivations('CREATE TABLE dst AS SELECT "a".v AS low, "A".v AS high FROM left_src "a" CROSS JOIN right_src "A"', "postgres")
    assert inputs(records[0]) == {("left_src", "v")}
    assert inputs(records[1]) == {("right_src", "v")}


def test_decoded_wrapper_expression_is_not_claimed_as_original_source() -> None:
    """Verify that decoded wrapper expression is not claimed as original source."""
    record = derivations("EXECUTE IMMEDIATE 'CREATE TABLE dst AS SELECT ''value'' AS x FROM src';", "snowflake")[0]
    assert record["expression"] == ""
    assert record["status"] == "unresolved"
    assert any("wrapper" in c.lower() for c in record["coverage"])


def test_named_window_does_not_claim_complete_dependencies() -> None:
    """Verify that named window does not claim complete dependencies."""
    record = derivations("CREATE TABLE dst AS SELECT SUM(amount) OVER w AS total FROM src WINDOW w AS (PARTITION BY account ORDER BY ts)")[0]
    assert record["status"] == "unresolved"
    assert any("named window" in c.lower() for c in record["coverage"])


def test_except_and_intersect_do_not_become_union_value_branches() -> None:
    """Verify that except and intersect do not become union value branches."""
    for operator in ("EXCEPT", "INTERSECT"):
        records = derivations(f"CREATE TABLE dst AS SELECT a FROM src {operator} SELECT a FROM other")
        assert len(records) == 1
        assert records[0]["target_column"] == "*"
        assert records[0]["status"] == "unresolved"
        assert inputs(records[0]) == set()
        assert any(operator in c for c in records[0]["coverage"])


def test_duplicate_projection_names_are_unresolved_without_conflating_targets() -> None:
    """Verify that duplicate projection names are unresolved without conflating targets."""
    records = derivations("CREATE TABLE dst AS SELECT a AS value, b AS value FROM src")
    assert len(records) == 2
    assert all(r["status"] == "unresolved" and r["target_column"] == "*" for r in records)
    assert all(any("duplicate" in c.lower() for c in r["coverage"]) for r in records)


def test_duplicate_intermediate_names_do_not_verify_downstream_reference() -> None:
    """Verify that duplicate intermediate names do not verify downstream reference."""
    records = derivations("CREATE TABLE dst AS WITH x AS (SELECT a AS value, b AS value FROM src) SELECT value FROM x")
    record = next(r for r in records if r["target_table"] == "dst")
    assert record["status"] == "unresolved"
    assert inputs(record) == set()


def test_lateral_projection_alias_does_not_become_physical_column() -> None:
    """Verify that lateral projection alias does not become physical column."""
    records = derivations("CREATE TABLE dst AS SELECT a AS x, x + 1 AS y FROM src", "snowflake")
    assert records[0]["status"] == "verified"
    assert records[1]["status"] == "unresolved"
    assert inputs(records[1]) == set()
    assert any("projection alias" in c.lower() for c in records[1]["coverage"])


def test_qualify_projection_alias_does_not_become_physical_filter() -> None:
    """Verify that qualify projection alias does not become physical filter."""
    record = derivations("CREATE TABLE dst AS SELECT a AS x FROM src QUALIFY x > 0", "snowflake")[0]
    assert inputs(record) == {("src", "a")}
    assert inputs(record, "row_filter") == set()
    assert record["status"] == "unresolved"


def test_base_table_column_alias_list_requires_schema_mapping() -> None:
    """Verify that base table column alias list requires schema mapping."""
    record = derivations("CREATE TABLE dst AS SELECT s.x AS z FROM src AS s(x, y)", "postgres")[0]
    assert inputs(record) == set()
    assert record["status"] == "unresolved"
    assert any("column alias" in c.lower() for c in record["coverage"])


def test_derived_table_column_alias_list_remains_supported() -> None:
    """Verify that derived table column alias list remains supported."""
    records = derivations("CREATE TABLE dst AS SELECT s.x AS z FROM (SELECT a, b FROM src) AS s(x, y)", "postgres")
    record = next(r for r in records if r["target_table"] == "dst")
    assert record["status"] == "verified"
    assert inputs(record) == {("s", "x")}


def test_base_table_alias_list_wildcard_cannot_expand_physical_names() -> None:
    """Verify that base table alias list wildcard cannot expand physical names."""
    record = derivations("CREATE TABLE dst AS SELECT s.* FROM src AS s(x, y)", "postgres")[0]
    assert record["wildcard_safe"] is False
    assert record["status"] == "unresolved"


def test_standard_sql_sibling_projection_aliases_do_not_hide_physical_inputs() -> None:
    """Verify that standard sql sibling projection aliases do not hide physical inputs."""
    for dialect in ("", "postgres"):
        records = derivations("CREATE TABLE dst AS SELECT a + b AS a, b + c AS b FROM src", dialect)
        assert all(record["status"] == "verified" for record in records)
        assert inputs(records[0]) == {("src", "a"), ("src", "b")}
        assert inputs(records[1]) == {("src", "b"), ("src", "c")}
