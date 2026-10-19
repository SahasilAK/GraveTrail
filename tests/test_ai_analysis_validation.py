"""Synthetic semantic gold: exact original evidence is necessary, never sufficient."""
import hashlib

import pytest

from dataforge.ai_validation import validate_project_response


def context(code, language="sql", job="job-a"):
    return {"unit": {"unit_id": "u", "file_id": "f", "path": "synthetic." + language,
                     "content_hash": hashlib.sha256(code.encode()).hexdigest(), "job_id": job,
                     "extension": "." + language, "code": code,
                     "start_offset": 0, "end_offset": len(code), "first": 1,
                     "last": code.count("\n") + 1}, "workspace_id": "w", "source_text": code, "settings": {}}


def response(ctx, **claims):
    unit = ctx["unit"]
    evidence = {key: unit[key] for key in ("unit_id", "file_id", "content_hash", "start_offset", "end_offset")}
    evidence.update(start_line=unit["first"], end_line=unit["last"])
    evidence["quote"] = ctx["source_text"][unit["start_offset"]:unit["end_offset"]]
    result = {"unit_id": unit["unit_id"], "coverage": {"status": "complete"}}
    for kind, items in claims.items():
        result[kind] = [{"evidence": evidence.copy(), **item} for item in items]
        if kind == "derivations":
            for item in result[kind]:
                offset = ctx["source_text"].find(item["expression"])
                item["expression_start_offset"] = max(offset, 0)
                item["expression_end_offset"] = max(offset, 0) + len(item["expression"])
    return result


def edge(source="raw.a", target="mart.b", operation="CREATE"):
    return {"source": source, "target": target, "operation": operation}


def derivation(expression="a.x + a.y AS total", **changes):
    return {"target_table": "mart.b", "target_column": "total", "expression": expression,
            "category": "expression", "scope": "", "branch": 0, "version": "", "ordinal": 0,
            "inputs": [{"table": "raw.a", "column": c, "role": "value"} for c in ("x", "y")],
            **changes}


def test_new_static_identifiers_and_complete_dependency_are_accepted():
    ctx = context("CREATE TABLE mart.b AS SELECT a.x + a.y AS total FROM raw.a a;")
    report = validate_project_response(response(ctx, relationships=[edge()], derivations=[derivation()]), ctx)
    assert [fact.kind for fact in report.accepted] == ["table_edge", "derivation"]
    assert not report.rejected and not report.unresolved
    assert all(f.status == "inferred" and f.evidence_key for f in report.accepted)


@pytest.mark.parametrize('role,accepted', [('row_filter', True), ('value_selection', False)])
def test_case_inside_where_keeps_row_filter_role(role, accepted):
    ctx = context('UPDATE mart.b SET total=a.x FROM raw.a a '
                  'WHERE CASE WHEN a.flag=1 THEN a.id ELSE a.other END=mart.b.id;')
    inputs = [{'table': 'raw.a', 'column': 'x', 'role': 'value'},
              *[{'table': 'raw.a', 'column': name, 'role': role if name == 'flag' else 'row_filter'}
                for name in ('flag', 'id', 'other')],
              {'table': 'mart.b', 'column': 'id', 'role': 'row_filter'}]
    claim = derivation('a.x', category='direct', inputs=inputs)
    result = validate_project_response(response(ctx, derivations=[claim]), ctx)
    assert bool(result.accepted) is accepted


@pytest.mark.parametrize("change", [
    {"inputs": [{"table": "raw.a", "column": "x", "role": "value"}]},
    {"inputs": [{"table": "raw.a", "column": c, "role": "join"} for c in ("x", "y")]},
    {"expression": "a.x - a.y AS total"}, {"branch": 1}, {"version": "wrong"},
])
def test_full_semantics_reject_missing_inputs_roles_expression_and_versions(change):
    ctx = context("CREATE TABLE mart.b AS SELECT a.x + a.y AS total FROM raw.a a;")
    report = validate_project_response(response(ctx, derivations=[derivation(**change)]), ctx)
    assert not report.accepted
    assert report.rejected or report.unresolved


@pytest.mark.parametrize("code,claim", [
    ("CREATE TABLE mart.b AS SELECT 'raw.a' AS label FROM real;", edge()),
    ("/* raw.a */ CREATE TABLE mart.b AS SELECT x FROM real;", edge()),
    ("CREATE TABLE mart.b AS WITH unused AS (SELECT * FROM raw.a) SELECT x FROM real;", edge()),
    ("CREATE TABLE mart.b AS SELECT x FROM raw.a;", edge("mart.b", "raw.a")),
])
def test_comments_literals_unreachable_ctes_and_wrong_direction_cannot_create_edges(code, claim):
    ctx = context(code)
    report = validate_project_response(response(ctx, relationships=[claim]), ctx)
    assert not report.accepted and report.rejected


def test_quote_with_removed_join_and_stale_hash_are_rejected():
    ctx = context("CREATE TABLE mart.b AS SELECT a.x FROM raw.a a JOIN raw.c c ON a.id=c.id;")
    data = response(ctx, relationships=[edge()])
    data["relationships"][0]["evidence"]["quote"] = "CREATE TABLE mart.b AS SELECT a.x FROM raw.a a;"
    assert validate_project_response(data, ctx).rejected
    data = response(ctx, relationships=[edge()])
    data["relationships"][0]["evidence"]["content_hash"] = "0" * 64
    assert validate_project_response(data, ctx).rejected


@pytest.mark.parametrize("code,claim", [
    ("CREATE TABLE mart.b AS SELECT mystery(a.x) AS total FROM raw.a a;",
     derivation("mystery(a.x) AS total", inputs=[{"table": "raw.a", "column": "x", "role": "value"}])),
    ("CREATE TABLE mart.b AS SELECT * FROM raw.a;", derivation("*", target_column="*", category="wildcard")),
    ("CREATE TABLE mart.b AS SELECT id AS total FROM raw.a JOIN raw.c ON raw.a.id=raw.c.id;",
     derivation("id AS total", inputs=[{"table": "raw.a", "column": "id", "role": "value"}])),
])
def test_unsupported_exact_evidence_remains_unresolved(code, claim):
    ctx = context(code)
    report = validate_project_response(response(ctx, derivations=[claim]), ctx)
    assert not report.accepted and report.unresolved


def test_distinct_same_line_statements_have_distinct_host_keys():
    code = "CREATE TABLE mart.b AS SELECT x FROM raw.a; CREATE TABLE mart.d AS SELECT x FROM raw.c;"
    ctx = context(code)
    report = validate_project_response(response(ctx, relationships=[edge(), edge("raw.c", "mart.d")]), ctx)
    assert len(report.accepted) == 2
    assert len({fact.evidence_key for fact in report.accepted}) == 2


def test_cross_job_temporary_keys_never_collide():
    code = "CREATE TEMP TABLE tmp AS SELECT x FROM raw.a;"
    left, right = context(code, job="left"), context(code, job="right")
    a = validate_project_response(response(left, relationships=[edge(target="tmp")]), left).accepted[0]
    b = validate_project_response(response(right, relationships=[edge(target="tmp")]), right).accepted[0]
    assert a.evidence_key != b.evidence_key


def test_static_update_gap_proves_assignment_and_context_roles():
    ctx = context("UPDATE mart.b SET total = a.x + a.y FROM raw.a a WHERE mart.b.id = a.id;")
    item = derivation("a.x + a.y", inputs=[
        {"table": "raw.a", "column": "x", "role": "value"},
        {"table": "raw.a", "column": "y", "role": "value"},
        {"table": "mart.b", "column": "id", "role": "row_filter"},
        {"table": "raw.a", "column": "id", "role": "row_filter"}])
    report = validate_project_response(response(ctx, derivations=[item]), ctx)
    assert len(report.accepted) == 1
    item["inputs"] = item["inputs"][:2]
    assert not validate_project_response(response(ctx, derivations=[item]), ctx).accepted


def test_static_merge_gap_accepts_one_matched_update_and_rejects_extra_branches():
    sql = "MERGE INTO mart.b b USING raw.a a ON b.id=a.id WHEN MATCHED THEN UPDATE SET total=a.x + a.y;"
    ctx = context(sql)
    item = derivation("a.x + a.y", inputs=[
        {"table": "raw.a", "column": "x", "role": "value"},
        {"table": "raw.a", "column": "y", "role": "value"},
        {"table": "mart.b", "column": "id", "role": "join"},
        {"table": "raw.a", "column": "id", "role": "join"}])
    assert validate_project_response(response(ctx, derivations=[item]), ctx).accepted
    ctx = context(sql[:-1] + " WHEN NOT MATCHED THEN INSERT (total) VALUES (a.x);")
    assert validate_project_response(response(ctx, derivations=[item]), ctx).unresolved


def test_sas_assignment_versions_and_scope_inputs_are_preserved():
    from dataforge.parsers.sas import parse_sas

    ctx = context("data mart.b; set raw.a; total=x+y; total=total*2; keep total; run;", "sas")
    records = parse_sas(ctx["source_text"]).operations[0].derivations
    claims = [{"target_table": r["target_table"], "target_column": r["target_column"],
               "expression": r["expression"], "category": r["category"], "scope": r["scope"],
               "branch": r["branch"], "version": r["target_version"], "ordinal": r["ordinal"],
               "inputs": r["inputs"]} for r in records]
    report = validate_project_response(response(ctx, derivations=claims), ctx)
    assert len(report.accepted) == 3
    claims[1]["inputs"][0]["version"] = "99"
    report = validate_project_response(response(ctx, derivations=claims), ctx)
    assert len(report.accepted) == 2 and report.rejected


def test_sas_runtime_macro_unchanged_exact_quote_is_not_semantic_proof():
    ctx = context('data mart.b; set raw.a; total=x*&unknown.; keep total; run;', "sas")
    item = derivation("total=x*&unknown.;", scope="data-step", version="1", inputs=[
        {"table": "raw.a", "column": "x", "role": "value"}])
    report = validate_project_response(response(ctx, derivations=[item]), ctx)
    assert report.unresolved and not report.accepted


def test_join_filter_and_rowset_inputs_cannot_be_flattened_to_values():
    from dataforge.parsers.sql import parse_sql

    sql = "CREATE TABLE mart.b AS SELECT a.x AS total FROM raw.a a JOIN raw.c c ON a.id=c.id WHERE c.flag=1;"
    ctx = context(sql)
    record = parse_sql(sql).operations[0].derivations[0]
    item = derivation(record["expression"], category=record["category"], inputs=record["inputs"])
    assert validate_project_response(response(ctx, derivations=[item]), ctx).accepted
    for value in item["inputs"]:
        value["role"] = "value"
    assert validate_project_response(response(ctx, derivations=[item]), ctx).rejected


def test_static_update_old_target_value_and_duplicate_assignments_abstain():
    ctx = context("UPDATE mart.b SET total=total+1;")
    item = derivation("total+1", inputs=[{"table": "mart.b", "column": "total", "role": "value"}])
    assert not validate_project_response(response(ctx, derivations=[item]), ctx).accepted
    ctx = context("UPDATE mart.b SET total=a.x, total=a.y FROM raw.a a;")
    item = derivation("a.x", category="direct", inputs=[{"table": "raw.a", "column": "x", "role": "value"}])
    assert not validate_project_response(response(ctx, derivations=[item]), ctx).accepted


def test_full_source_substring_and_line_bounds_are_host_checked():
    ctx = context("CREATE TABLE mart.b AS SELECT x FROM raw.a;")
    ctx["source_text"] = "-- shifted\n" + ctx["source_text"]
    report = validate_project_response(response(ctx, relationships=[edge()]), ctx)
    assert report.rejected and not report.accepted


def test_empty_response_cannot_claim_complete_semantic_coverage_of_real_operations():
    ctx = context("CREATE TABLE mart.b AS SELECT x FROM raw.a;")
    data = response(ctx)
    data["coverage"]["status"] = "no_operations"
    report = validate_project_response(data, ctx)
    assert report.coverage.status == "partial"
    assert "no_supported_claims" in report.coverage.unsupported
