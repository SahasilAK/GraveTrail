"""Development failures reduced to independent positive and deceptive-negative cases."""


from dataforge.ai_validation import validate_project_response
from dataforge.parsers.sql import parse_sql
from tests.test_ai_analysis_validation import context, edge, response


def test_invalid_sas_literals_never_establish_claims():
    code = "proc sql; create table mart.b as select id from raw.a where stamp >= '01FAKE25'd; quit;"
    ctx = context(code, 'sas')
    assert not validate_project_response(response(ctx, relationships=[edge()]), ctx).accepted


def test_sas_usage_cannot_drop_typed_literal_suffix():
    code = "proc sql; create table mart.b as select a.id from raw.a a where a.stamp >= '01JAN2025'd; quit;"
    ctx = context(code, 'sas')
    column = {'table': 'raw.a', 'column': 'stamp', 'context': 'WHERE', 'alias': 'a',
              'expression': "a.stamp >= '01JAN2025'"}
    assert not validate_project_response(response(ctx, columns=[column]), ctx).accepted
    column['expression'] += 'd'
    assert validate_project_response(response(ctx, columns=[column]), ctx).accepted


def test_merge_derived_using_activates_only_reachable_sources():
    code = ("MERGE INTO mart.b b USING (WITH unused AS (SELECT id FROM fake.secret) "
            "SELECT id, max(x) AS x FROM raw.a GROUP BY id) incoming ON b.id=incoming.id "
            "WHEN MATCHED THEN UPDATE SET total=incoming.x;")
    parsed = parse_sql(code)
    assert len(parsed.operations) == 1
    assert {r.name for r in parsed.operations[0].sources} == {'raw.a'}
    ctx = context(code)
    report = validate_project_response(response(ctx, relationships=[edge(operation='MERGE'), edge('fake.secret', operation='MERGE')]), ctx)
    assert len(report.accepted) == 1 and report.accepted[0].source == 'raw.a'
    assert report.rejected


def test_valid_merge_inner_alias_shadow_cannot_steal_target_read():
    code = ('MERGE INTO mart.b a USING (SELECT id FROM raw.a a) incoming ON a.id=incoming.id '
            'WHEN MATCHED THEN UPDATE SET total=a.id;')
    ctx = context(code)
    column = {'table': 'raw.a', 'column': 'id', 'context': 'UPDATE',
              'alias': 'a', 'expression': 'total = a.id'}
    assert not validate_project_response(response(ctx, columns=[column]), ctx).accepted
    column['table'] = 'mart.b'
    assert validate_project_response(response(ctx, columns=[column]), ctx).accepted
