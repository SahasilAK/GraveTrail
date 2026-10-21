"""Development failures reduced to independent positive and deceptive-negative cases."""
from contextlib import closing

import pytest

from dataforge.ai_validation import validate_project_response
from dataforge.parsers.sas import parse_sas
from dataforge.parsers.sql import parse_sql
from tests.test_ai_analysis_validation import context, edge, response


@pytest.mark.parametrize('literal', ["'01JAN2025'd", "'01jan25'D", "'12:30:01't", "'01JAN2025:12:30:01'dt"])
def test_sas_typed_literals_keep_aggregate_table_dependencies_and_original(literal):
    code = ("proc sql; create table mart.b as select a.id, sum(a.x) as total "
            "from raw.a a left join raw.c c on a.id=c.id "
            f"where a.stamp >= {literal} group by a.id; quit;")
    parsed = parse_sas(code)
    assert len(parsed.operations) == 1
    operation = parsed.operations[0]
    assert {r.name for r in operation.sources} == {'raw.a', 'raw.c'}
    assert literal in operation.code
    ctx = context(code, 'sas')
    report = validate_project_response(response(ctx, relationships=[edge(), edge('raw.c')]), ctx)
    assert len(report.accepted) == 2


@pytest.mark.parametrize('literal', ["'32JAN2025'd", "'01FAKE25'd", "'25:00:00't", "'01JAN2025'unknown"])
def test_invalid_sas_literals_never_establish_claims(literal):
    code = f'proc sql; create table mart.b as select id from raw.a where stamp >= {literal}; quit;'
    ctx = context(code, 'sas')
    assert not validate_project_response(response(ctx, relationships=[edge()]), ctx).accepted


def test_sas_plain_string_alias_and_ordinary_sql_are_unchanged():
    parsed = parse_sas("proc sql; create table mart.b as select '01JAN2025' d from raw.a; quit;")
    assert parsed.operations
    assert not parse_sql("create table mart.b as select id from raw.a where stamp >= '01JAN2025'd;").operations


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


def test_merge_derived_using_does_not_guess_outer_column_ownership():
    parsed = parse_sql('MERGE INTO mart.b b USING (SELECT id, x FROM raw.a) incoming '
                       'ON b.id=incoming.id WHEN MATCHED THEN UPDATE SET total=incoming.x;')
    assert not any(u.table == 'raw.a' and u.context == 'MERGE' for u in parsed.operations[0].usages)
    assert not any(d['status'] == 'verified' for d in parsed.operations[0].derivations)


@pytest.mark.parametrize('sql,expression,usage_context', [
    ('MERGE INTO mart.b b USING (SELECT id FROM raw.a a) incoming ON b.id=incoming.id '
     'WHEN MATCHED THEN UPDATE SET total=a.id;', 'total = a.id', 'UPDATE'),
    ('UPDATE mart.b SET total=(SELECT max(a.id) FROM raw.a a) WHERE a.id=1;', 'a.id = 1', 'WHERE'),
    ('DELETE FROM mart.b WHERE EXISTS (SELECT 1 FROM raw.a a) AND a.id=1;', 'a.id = 1', 'WHERE'),
])
def test_inner_query_alias_cannot_establish_outer_dml_usage(sql, expression, usage_context):
    ctx = context(sql)
    column = {'table': 'raw.a', 'column': 'id', 'context': usage_context,
              'alias': 'a', 'expression': expression}
    assert not validate_project_response(response(ctx, columns=[column]), ctx).accepted


def test_valid_merge_inner_alias_shadow_cannot_steal_target_read():
    code = ('MERGE INTO mart.b a USING (SELECT id FROM raw.a a) incoming ON a.id=incoming.id '
            'WHEN MATCHED THEN UPDATE SET total=a.id;')
    ctx = context(code)
    column = {'table': 'raw.a', 'column': 'id', 'context': 'UPDATE',
              'alias': 'a', 'expression': 'total = a.id'}
    assert not validate_project_response(response(ctx, columns=[column]), ctx).accepted
    column['table'] = 'mart.b'
    assert validate_project_response(response(ctx, columns=[column]), ctx).accepted


@pytest.mark.parametrize('language', ['sql', 'sas'])
def test_update_scalar_subquery_is_active_but_unused_cte_is_not(language):
    sql = ('WITH unused AS (SELECT x FROM fake.secret) UPDATE mart.b SET total='
           '(SELECT max(a.x) FROM raw.a a WHERE a.id=mart.b.id);')
    code = 'proc sql; ' + sql + ' quit;' if language == 'sas' else sql
    parsed = parse_sas(code) if language == 'sas' else parse_sql(code)
    assert len(parsed.operations) == 1
    assert {r.name for r in parsed.operations[0].sources} == {'raw.a'}
    ctx = context(code, language)
    result = validate_project_response(response(ctx, relationships=[edge(operation='UPDATE')]), ctx)
    assert len(result.accepted) == 1


def test_delete_exists_reachable_query_retains_input():
    code = 'DELETE FROM mart.b WHERE EXISTS (SELECT 1 FROM raw.a a WHERE a.id=mart.b.id);'
    assert {r.name for r in parse_sql(code).operations[0].sources} == {'raw.a'}


@pytest.mark.parametrize('symbol', ['VALIDATOR_VERSION', 'PARSER_VERSION'])
def test_validator_upgrade_invalidates_continuation_before_any_new_call(tmp_path, monkeypatch, symbol):
    from dataforge.ai_analysis_models import AnalysisRequest, ProjectLineageResponse, UnitAttemptResult
    from dataforge.analysis_service import run_analysis
    from dataforge.ingestion import Importer
    from dataforge.llm import Profile
    from dataforge.store import Store

    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('upgrade')
        Importer(store, workspace).files([('q.sql', b'SELECT 1; SELECT 2;')], {'.sql'})
        profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=0, context_chars=100000)
        store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', workspace, 'm', profile.model_dump_json()])
        store.set_setting(workspace, 'default_profile', 'p')
        store.set_setting(workspace, 'max_context_chars', 100000)
        calls = []
        def extract(s, w, unit, task, execution):
            calls.append(unit.unit_id)
            execution.before_attempt(profile)
            return UnitAttemptResult(unit_id=unit.unit_id, task=task, result=ProjectLineageResponse(unit_id=unit.unit_id))
        monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', extract)
        first = run_analysis(store, workspace, AnalysisRequest(mode='hybrid', auto_continue=False, max_provider_attempts=1))
        assert first.status == 'awaiting_continuation'
        import dataforge.analysis_service as service
        monkeypatch.setattr(service, symbol, 'upgrade', raising=False)
        result = run_analysis(store, workspace, AnalysisRequest(mode='hybrid', resume_run_id=first.run_id))
        assert result.status == 'stale'
        assert len(calls) == 1 and not store.rows('SELECT * FROM analysis_runs')
