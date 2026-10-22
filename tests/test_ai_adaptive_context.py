import json
import zipfile
from pathlib import Path

import pytest

from dataforge.ai_analysis_models import AnalysisRequest
from dataforge.analysis_service import _prepare, preview_analysis
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.store import Store


def workspace(tmp_path, files, *, limit=8000):
    store = Store(tmp_path)
    w = store.create_workspace('adaptive context')
    Importer(store, w).files(files, {'.sql', '.sas'})
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='m', retries=0)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'm', profile.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', limit)
    return store, w


def test_small_real_fixture_is_not_blocked_by_schema_overhead(tmp_path):
    with zipfile.ZipFile(Path('tests/sample_data/banking_legacy_sql_2114_lineage_stress_test.zip')) as archive:
        path = '00_reference/ref_aml_reasons.sql'
        source = archive.read(path)
    store, w = workspace(tmp_path, [(path, source)])
    preview = preview_analysis(store, w, AnalysisRequest(mode='ai', additional_ai_review=True))
    assert preview['valid'], preview['blocked']
    allowance = preview['allowances'][0]
    assert allowance['source_characters'] < 8000
    assert allowance['required_characters'] > allowance['source_characters']
    assert allowance['character_limit'] == 8000
    store.close()


def test_source_windows_checkpoint_resume_and_publish_one_original_writer(tmp_path):
    import httpx

    from dataforge.analysis_service import run_analysis
    code = 'CREATE TABLE b AS SELECT a.id AS id FROM raw.a a WHERE a.id IN (' + ','.join(str(i) for i in range(1800)) + ');'
    store, w = workspace(tmp_path, [('q.sql', code.encode())], limit=2000)
    seen = []
    def provider(request):
        text = json.loads(request.content)['messages'][1]['content']
        ctx = json.loads(text[text.index('{'):])
        assert 'items' not in ctx  # 2048 output cap keeps these requests independent.
        uid = ctx['unit']['unit_id']
        seen.append(uid)
        reference = next(r for r in ctx['expression_references'] if r['kind'] == 'projection')
        payload = {'unit_id': uid, 'coverage': {'status': 'complete'},
            'relationships': [{'source': 'raw.a', 'target': 'b', 'operation': 'CREATE', 'evidence': {'unit_id': uid}}],
            'derivations': [{'target_table': 'b', 'target_column': 'id', 'expression_reference': reference['reference_id'],
                'category': 'direct', 'inputs': [{'table': 'raw.a', 'column': 'id'},
                    {'table': 'raw.a', 'column': 'id', 'role': 'row_filter'}], 'evidence': {'unit_id': uid}}]}
        return httpx.Response(200, json={'message': {'content': json.dumps(payload)}})
    transport = httpx.MockTransport(provider)
    first = run_analysis(store, w, AnalysisRequest(mode='ai', auto_continue=False, max_provider_attempts=1), transport=transport)
    assert first.status == 'awaiting_continuation', first.reasons
    assert len(seen) == 1
    store.close()
    store = Store(tmp_path)
    result = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id,
        max_provider_attempts=2000), transport=transport)
    assert result.status == 'committed', result.reasons
    assert len(seen) > 1 and len(seen) == len(set(seen))
    assert len(store.edges(w)) == 1
    assert store.rows('SELECT count(*) AS n FROM column_derivations')[0]['n'] == 1
    assert result.counts['coverage_gaps'] > 0
    store.close()


@pytest.mark.parametrize('extension,code', [
    ('.sql', 'CREATE TABLE b AS SELECT ' + ' UNION ALL SELECT '.join(str(i) for i in range(1000)) + ';'),
    ('.sas', 'data work.b; set raw.a;\n' + '\n'.join(f'x{i}=x{i-1}+1;' for i in range(1600)) + '\nrun;'),
    ('.sas', '%macro big;\n' + '/* retained original source */\n' * 8000 + '%mend;'),
], ids=['sql-union', 'sas-data', 'sas-large-macro'])
def test_indivisible_sources_are_covered_by_bounded_persistent_views(tmp_path, extension, code):
    from dataforge.ai_semantic import source_view
    store, w = workspace(tmp_path, [('q' + extension, code.encode())], limit=2000)
    prepared, plan, execution, preview = _prepare(store, w, AnalysisRequest(mode='ai'))
    assert preview['valid'], preview['blocked'][:3]
    assert len(plan.units) > 1
    assert all(a['source_characters'] <= 2000 for a in preview['allowances'])
    ranges = sorted({(s['start_offset'], s['end_offset']) for u in plan.units for s in source_view(u)})
    cursor = plan.units[0].start_offset
    for start, end in ranges:
        assert start <= cursor
        cursor = max(cursor, end)
        assert prepared.sources[0].code[start:end] == code[start:end]
    assert cursor == plan.units[0].end_offset
    assert all(u.source_focus and u.code == plan.units[0].code for u in plan.units)
    store.close()


def test_large_dbt_project_context_is_paged_instead_of_rejected(tmp_path):
    store, w = workspace(tmp_path, [], limit=2000)
    Importer(store, w).files([('dbt_project.yml', b'name: shop\nvars:\n  long_value: ' + b'x' * 22000),
        ('models/a.sql', b'select 1 as id')], set(), source_kind='dbt')
    _, plan, _, preview = _prepare(store, w, AnalysisRequest(mode='ai'))
    assert preview['valid'], preview['blocked'][:3]
    assert len(plan.units) > 1 and all(u.source_kind == 'dbt' for u in plan.units)
    assert all(a['source_characters'] <= 2000 for a in preview['allowances'])
    store.close()


def test_partial_view_cannot_certify_full_coverage_or_cite_hidden_expression(tmp_path):
    from dataforge.ai_analysis_models import EvidenceCitation, ProjectLineageResponse, ValidationContext
    from dataforge.ai_semantic import source_view
    from dataforge.ai_validation import validate_project_response
    code = 'CREATE TABLE b AS SELECT ' + ' UNION ALL SELECT '.join(f'{i} AS id' for i in range(300)) + ';'
    store, w = workspace(tmp_path, [('q.sql', code.encode())], limit=2000)
    prepared, plan, _, preview = _prepare(store, w, AnalysisRequest(mode='ai'))
    assert preview['valid']
    unit = plan.units[0]
    visible = source_view(unit)
    context = ValidationContext(unit=unit, workspace_id=w, source_text=prepared.sources[0].code)
    report = validate_project_response(ProjectLineageResponse(unit_id=unit.unit_id,
        coverage={'status': 'complete'}), context)
    assert report.coverage.status == 'partial'
    assert 'partitioned_source_or_context' in report.coverage.unsupported
    start = code.index('250 AS id')
    assert not any(s['start_offset'] <= start < start + 9 <= s['end_offset'] for s in visible)
    response = ProjectLineageResponse(unit_id=unit.unit_id, derivations=[{
        'target_table': 'b', 'target_column': 'id', 'expression': '250 AS id', 'category': 'constant',
        'branch': 250, 'expression_start_offset': start, 'expression_end_offset': start + 9,
        'evidence': EvidenceCitation.from_unit(unit)}])
    report = validate_project_response(response, context)
    assert not report.accepted
    assert report.rejected[0].reason == 'outside_source_view'
    store.close()


def test_model_smaller_than_protocol_fails_once_instead_of_splitting_every_character(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
    store, w = workspace(tmp_path, [('q.sql', ("SELECT '" + 'x' * 10000 + "' AS text;").encode())])
    profile = Profile.model_validate_json(store.rows('SELECT config FROM llm_profiles')[0]['config'])
    profile.model_capabilities = bind_capabilities(ModelCapabilities(input_tokens=1000, window='separate'), profile)
    store.execute('UPDATE llm_profiles SET config=?', [profile.model_dump_json()])
    original = service.preview_analysis_routes
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        assert len(calls) <= 8, 'A too-small protocol must not explode into character tasks'
        return original(*args, **kwargs)
    monkeypatch.setattr(service, 'preview_analysis_routes', counted)
    preview = service.preview_analysis(store, w, AnalysisRequest(mode='ai'))
    assert not preview['valid']
    assert any(b['reason'] == 'complete_prompt_exceeds_model_capacity' for b in preview['blocked'])
    store.close()


def test_projection_and_source_context_views_preserve_both_host_identities(tmp_path):
    code = ('CREATE TABLE b AS SELECT a.id AS id, a.x AS x FROM raw.a a WHERE a.id IN ('
            + ','.join(str(i) for i in range(1800)) + ');')
    store, w = workspace(tmp_path, [('q.sql', code.encode())], limit=2000)
    _, plan, _, preview = _prepare(store, w, AnalysisRequest(mode='ai'))
    assert preview['valid'], preview['blocked'][:3]
    assert any(u.focus and u.source_focus for u in plan.units)
    assert all(a['source_characters'] <= 2000 for a in preview['allowances'])
    store.close()


def test_character_minimum_stops_irreducible_view_expansion(tmp_path, monkeypatch):
    import dataforge.analysis_service as service
    store, w = workspace(tmp_path, [('q.sql', ("SELECT '" + 'x' * 10000 + "' AS text;").encode())], limit=500)
    store.set_setting(w, 'macros', {'k' * 1000: 'x' * 1000})
    original = service.preview_analysis_routes
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        assert len(calls) <= 100
        return original(*args, **kwargs)
    monkeypatch.setattr(service, 'preview_analysis_routes', counted)
    result = service.preview_analysis(store, w, AnalysisRequest(mode='ai'))
    assert not result['valid']
    store.close()


def test_review_and_resolution_domain_payloads_count_toward_character_allowance():
    from dataforge.ai_budget import request_allowance
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='m')
    for key, value in [('candidates', [{'expression': 'x' * 10000}]), ('resolution', {'source': 'x' * 10000})]:
        payload = json.dumps({'unit': {'code': 'select 1;'}, 'catalog': [], key: value})
        result = request_allowance(profile, 'system', payload, privacy_chars=500)
        assert not result.valid and result.source_characters > 10000


def test_generic_views_do_not_reintroduce_their_own_declaration_context(tmp_path):
    code = 'CREATE TABLE b AS SELECT ' + ' UNION ALL SELECT '.join(str(i) for i in range(300)) + ';'
    store, w = workspace(tmp_path, [('q.sql', code.encode())], limit=2000)
    _, plan, _, preview = _prepare(store, w, AnalysisRequest(mode='ai'))
    assert preview['valid']
    assert all(not plan.context_for(u) for u in plan.units)
    store.close()


def test_hidden_table_and_usage_cannot_be_attributed_to_a_source_view(tmp_path):
    from dataforge.ai_analysis_models import EvidenceCitation, ProjectLineageResponse, ValidationContext
    from dataforge.ai_semantic import source_view
    from dataforge.ai_validation import validate_project_response
    code = ('CREATE TABLE b AS ' + ' UNION ALL '.join('SELECT a.id FROM ' +
        ('private.secret' if i == 100 else 'raw.a') + ' a' for i in range(250)) + ';')
    store, w = workspace(tmp_path, [('q.sql', code.encode())], limit=2000)
    prepared, plan, _, preview = _prepare(store, w, AnalysisRequest(mode='ai'))
    assert preview['valid']
    unit = next(u for u in plan.units if 'private.secret' not in ''.join(s['code'] for s in source_view(u)))
    evidence = EvidenceCitation.from_unit(unit)
    report = validate_project_response(ProjectLineageResponse(unit_id=unit.unit_id,
        relationships=[{'source': 'private.secret', 'target': 'b', 'operation': 'CREATE', 'evidence': evidence}],
        columns=[{'table': 'private.secret', 'column': 'id', 'context': 'SELECT', 'evidence': evidence}]),
        ValidationContext(unit=unit, workspace_id=w, source_text=prepared.sources[0].code))
    assert not report.accepted
    assert {d.reason for d in report.rejected} == {'outside_source_view'}
    store.close()


@pytest.mark.parametrize('limit,review,resume', [(2000, False, True), (8000, False, False), (8000, True, False)])
def test_long_expression_dependencies_compose_from_saved_components(tmp_path, limit, review, resume, monkeypatch):
    """Transport fixture supplies known components; this tests composition, not LLM accuracy."""
    import re

    import httpx

    from dataforge.analysis_service import run_analysis
    code = ('CREATE TABLE b AS SELECT CASE ' + ' '.join(f'WHEN a.k{i}={i} THEN a.v{i}' for i in range(150))
            + ' ELSE a.y END AS v FROM raw.a a;')
    store, w = workspace(tmp_path, [('q.sql', code.encode())], limit=limit)
    components = []
    seen = set()
    import dataforge.ai_reconciliation as reconciliation
    normalized = []
    original = reconciliation.normalize_parser_facts
    def count_parent(parsed, context):
        assert context.unit.source_focus is None
        normalized.append(context.unit.unit_id)
        return original(parsed, context)
    monkeypatch.setattr(reconciliation, 'normalize_parser_facts', count_parent)
    def provider(request):
        body = json.loads(request.content)
        ctx = json.loads(body['messages'][1]['content'].split('\n\n', 1)[1])
        assert 'items' not in ctx
        uid = ctx['unit']['unit_id']
        if 'candidates' in ctx:
            issued = {r['reference_id'] for r in ctx['expression_references']}
            assert all(c.get('expression_references') and set(c['expression_references']) <= issued
                for c in ctx['candidates'])
            payload = {'decisions': [{'candidate_id': candidate['candidate_id'], 'decision': 'supported',
                'evidence': [{'unit_id': uid}]} for candidate in ctx['candidates']]}
            return httpx.Response(200, json={'message': {'content': json.dumps(payload)}})
        refs = ctx.get('partial_expression_references', [])
        assert refs, 'A long expression must remain addressable across its views'
        assert uid not in seen
        seen.add(uid)
        text = '\n'.join(s['code'] for s in ctx['source_segments'])
        inputs = [{'table': 'raw.a', 'column': name, 'role': 'value_selection' if name.startswith('k') else 'value'}
                  for name in sorted(set(re.findall(r'a\.(k\d+|v\d+|y)\b', text)))]
        components.append(inputs)
        payload = {'unit_id': uid, 'derivations': [{'target_table': 'b', 'target_column': 'v',
            'category': 'case', 'fragment': True, 'expression_reference': refs[0]['reference_id'],
            'inputs': inputs, 'evidence': {'unit_id': uid}}]}
        return httpx.Response(200, json={'message': {'content': json.dumps(payload)}})
    transport = httpx.MockTransport(provider)
    result = run_analysis(store, w, AnalysisRequest(mode='ai', additional_ai_review=review,
        auto_continue=not resume, max_provider_attempts=1 if resume else None), transport=transport)
    if resume:
        assert result.status == 'awaiting_continuation'
        assert store.rows('SELECT count(*) AS n FROM column_derivations')[0]['n'] == 0
        store.close()
        store = Store(tmp_path)
        result = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=result.run_id,
            max_provider_attempts=2000), transport=transport)
    assert result.status == 'committed', result.reasons
    assert len(components) > 1
    assert store.rows('SELECT count(*) AS n FROM column_derivations')[0]['n'] == 1
    assert store.rows('SELECT count(*) AS n FROM column_dependencies')[0]['n'] == 301
    assert store.rows('SELECT count(*) AS n FROM column_references WHERE table_name=?', ['b'])[0]['n'] == 1
    assert len(normalized) == 1
    # A composed expression inherits its component review; it must never be
    # submitted whole on a later build, including when review is newly requested.
    calls = len(seen)
    def no_network(request):
        pytest.fail('Reviewed saved components must be reused without provider calls')
    again = AnalysisRequest(mode='ai', additional_ai_review=review)
    preview = preview_analysis(store, w, again)
    assert preview['valid'], preview['blocked'][:3]
    reused = run_analysis(store, w, again, transport=httpx.MockTransport(no_network))
    assert reused.status == 'committed', reused.reasons
    assert len(seen) == calls
    assert store.rows('SELECT count(*) AS n FROM column_dependencies')[0]['n'] == 301
    if not review and limit == 8000:
        def reject_components(request):
            ctx = json.loads(json.loads(request.content)['messages'][1]['content'].split('\n\n', 1)[1])
            assert 'candidates' in ctx, 'Saved extraction must survive a new review policy'
            return httpx.Response(200, json={'message': {'content': json.dumps({'decisions': [
                {'candidate_id': c['candidate_id'], 'decision': 'insufficient_evidence'} for c in ctx['candidates']]})}})
        reviewed = run_analysis(store, w, AnalysisRequest(mode='ai', additional_ai_review=True),
            transport=httpx.MockTransport(reject_components))
        assert reviewed.status == 'committed', reviewed.reasons
        assert store.rows('SELECT count(*) AS n FROM column_dependencies')[0]['n'] == 0
    store.close()


def test_repeated_union_branches_fit_response_array_capacity(tmp_path):
    from dataforge.ai_citations import source_references
    code = 'CREATE TABLE b AS ' + ' UNION ALL '.join(f'SELECT {i} AS id' for i in range(250)) + ';'
    store, w = workspace(tmp_path, [('q.sql', code.encode())])
    _, plan, _, preview = _prepare(store, w, AnalysisRequest(mode='ai'))
    assert preview['valid'], preview['blocked'][:3]
    assert all(len(source_references(u, partial=True)) <= 100 for u in plan.units)
    store.close()


def test_visible_quoted_identifiers_preserve_spaces_and_escaped_delimiters():
    from dataforge.ai_analysis_models import AnalysisUnit
    from dataforge.ai_source_views import identifier_name, visible_names
    code = 'SELECT a."key 0", a."escaped""name", [odd]]name], `tick``name` FROM "raw data"."a table";'
    unit = AnalysisUnit(unit_id='u', file_id='f', content_hash='h', job_id='j', extension='.sql',
        path='q.sql', code=code, start_offset=0, end_offset=len(code), first=1, last=1)
    names = visible_names(unit, [{'start_offset': 0, 'end_offset': len(code)}])
    for name in ['"key 0"', '"escaped""name"', '[odd]]name]', '`tick``name`', '"raw data"."a table"']:
        assert identifier_name(name) in names


@pytest.mark.parametrize('code', [
    'UPDATE b SET c=' + '+'.join(f'a.x{i}' for i in range(150)) + ' FROM a;',
    'CREATE TABLE b AS SELECT CASE ' + ' '.join(f'WHEN a."key {i}"={i} THEN a."value {i}"' for i in range(80))
        + ' ELSE a.y END AS v FROM raw.a a;',
], ids=['update', 'quoted-case'])
def test_source_components_use_complete_validator_semantics(tmp_path, code):
    from dataforge.ai_analysis_models import (
        DerivationCandidate,
        EvidenceCitation,
        ProjectLineageResponse,
        ValidationContext,
    )
    from dataforge.ai_semantic import source_view
    from dataforge.ai_source_views import identifier_name, visible_names
    from dataforge.ai_validation import _bounded_dml, validate_project_response
    from dataforge.parsers.sql import parse_sql
    store, w = workspace(tmp_path, [('q.sql', code.encode())], limit=2000)
    prepared, plan, _, preview = _prepare(store, w, AnalysisRequest(mode='ai'))
    assert preview['valid'], preview['blocked'][:3]
    unit = plan.units[0]
    parsed = parse_sql(code)
    context = ValidationContext(unit=unit, workspace_id=w, source_text=prepared.sources[0].code, parser_result=parsed)
    operation = parsed.operations[0]
    record = next(r for r in [*operation.derivations, *_bounded_dml(operation, context)] if r['status'] == 'verified')
    names = visible_names(unit, source_view(unit))
    inputs = [i for i in record['inputs'] if identifier_name(i['column']) in names]
    assert inputs
    start = code.index(record['expression'])
    claim = DerivationCandidate(target_table=record['target_table'], target_column=record['target_column'],
        expression=record['expression'], category=record['category'], ordinal=record.get('ordinal', 0),
        expression_start_offset=start, expression_end_offset=start+len(record['expression']), inputs=inputs,
        fragment=True, evidence=EvidenceCitation.from_unit(unit))
    report = validate_project_response(ProjectLineageResponse(unit_id=unit.unit_id, derivations=[claim]), context)
    assert report.fragments, report.rejected
    store.close()


def test_per_build_character_override_is_explicit_and_does_not_mutate_settings(tmp_path):
    store, w = workspace(tmp_path, [('q.sql', b'select 1;')], limit=8000)
    preview = preview_analysis(store, w, AnalysisRequest(mode='ai', max_context_chars=24000))
    assert preview['valid']
    assert preview['allowances'][0]['character_limit'] == 24000
    assert store.setting(w, 'max_context_chars') == 8000
    profile = json.loads(store.rows('SELECT config FROM llm_profiles')[0]['config'])
    assert profile['context_chars'] == 16000
    store.close()
