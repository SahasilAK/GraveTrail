import pytest

from dataforge.ai_analysis_models import (
    AnalysisRequest,
    Coverage,
    DerivationCandidate,
    DerivationInput,
    EvidenceCitation,
    ProjectLineageResponse,
    TableRelationship,
    UnitAttemptResult,
)
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def project(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('Project AI')
    Importer(store, w).files([('q.sql', b'CREATE TABLE mart.x AS SELECT id FROM raw.a;')], {'.sql'})
    from dataforge.llm import Profile
    p = Profile(provider='Ollama', base_url='http://localhost:11434', model='test', context_chars=100000)
    store.execute('INSERT INTO llm_profiles VALUES (?,?,?,?)', ['p', w, 'test', p.model_dump_json()])
    store.set_setting(w, 'default_profile', 'p')
    store.set_setting(w, 'max_context_chars', 100000)
    yield store, w
    store.close()


def fake_response(store, w, unit, task, execution):
    evidence = EvidenceCitation.from_unit(unit)
    at = unit.start_offset + unit.code.index('id')
    response = ProjectLineageResponse(unit_id=unit.unit_id, coverage=Coverage(status='complete'),
        relationships=[TableRelationship(source='raw.a', target='mart.x', operation='CREATE', evidence=evidence)],
        derivations=[DerivationCandidate(target_table='mart.x', target_column='id', expression='id',
            category='direct', inputs=[DerivationInput(table='raw.a', column='id')], evidence=evidence,
            expression_start_offset=at, expression_end_offset=at + 2)])
    return UnitAttemptResult(unit_id=unit.unit_id, task=task, result=response, usage_known=True,
                             usage={'input_tokens': 10, 'output_tokens': 5})


def test_hybrid_build_publishes_columns_and_cache_revalidates_offline(project, monkeypatch):
    from dataforge.analysis_service import preview_analysis, run_analysis
    store, w = project
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', fake_response)
    preview = preview_analysis(store, w, AnalysisRequest(mode='hybrid'))
    assert preview['valid'] and preview['units'] == 1
    report = run_analysis(store, w, AnalysisRequest(mode='hybrid'))
    assert report.status == 'committed' and report.complete
    assert len(store.edges(w)) == 1
    assert store.rows('SELECT count(*) AS n FROM column_derivations')[0]['n'] == 1
    assert store.rows('SELECT count(*) AS n FROM analysis_fact_support')[0]['n'] >= 2
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', lambda *a: pytest.fail('cached build sent AI'))
    cached = run_analysis(store, w, AnalysisRequest(mode='hybrid'))
    assert cached.status == 'committed' and cached.counts['cache_hits'] == 1


def test_repeated_cached_builds_rebind_all_historical_support(project, monkeypatch):
    from dataforge.analysis_service import run_analysis
    store, w = project
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', fake_response)
    home = store.home
    for index in range(6):
        if index:
            store = Store(home)
        report = run_analysis(store, w, AnalysisRequest(mode='hybrid'))
        assert report.status == 'committed', report.reasons
        assert len(store.edges(w)) == 1
        assert store.rows('SELECT COUNT(*) AS n FROM analysis_fact_support')[0]['n'] == 2 * (index + 1)
        store.close()


def test_source_changed_during_ai_retains_previous_graph(project, monkeypatch):
    from dataforge.analysis_service import run_analysis
    store, w = project
    analyze(store, w)
    old = store.edges(w)

    def changed(*args):
        result = fake_response(*args)
        Importer(store, w).files([('q.sql', b'CREATE TABLE mart.y AS SELECT other FROM raw.b;')], {'.sql'})
        return result

    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', changed)
    report = run_analysis(store, w, AnalysisRequest(mode='hybrid'))
    assert report.status == 'stale' and not report.complete
    assert store.edges(w) == old


def test_cancelled_build_and_invalid_transport_never_replace_graph(project, monkeypatch):
    from dataforge.analysis_service import run_analysis
    store, w = project
    analyze(store, w)
    old = store.edges(w)
    cancelled = run_analysis(store, w, AnalysisRequest(mode='ai'), cancelled=lambda: True)
    assert cancelled.status == 'cancelled' and store.edges(w) == old
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', lambda *a:
        UnitAttemptResult(unit_id=a[2].unit_id, task='project_lineage', outcome='quarantined', reason='bad_json'))
    failed = run_analysis(store, w, AnalysisRequest(mode='ai'))
    assert failed.status == 'failed' and store.edges(w) == old


def test_parser_mode_needs_no_provider(project, monkeypatch):
    from dataforge.analysis_service import run_analysis
    store, w = project
    store.execute('DELETE FROM llm_profiles')
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', lambda *a: pytest.fail('parser sent AI'))
    report = run_analysis(store, w, AnalysisRequest())
    assert report.status == 'committed' and len(store.edges(w)) == 1


def test_unsupported_coverage_and_rejected_response_are_not_stored_as_success(project, monkeypatch):
    from dataforge.analysis_service import run_analysis
    store, w = project

    def unsupported(*args):
        unit = args[2]
        response = ProjectLineageResponse(unit_id=unit.unit_id, coverage=Coverage(status='unsupported'),
            relationships=[TableRelationship(source='raw.a', target='fabricated-private-marker', operation='CREATE',
                                               evidence=EvidenceCitation.from_unit(unit))])
        return UnitAttemptResult(unit_id=unit.unit_id, task='project_lineage', result=response)

    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', unsupported)
    report = run_analysis(store, w, AnalysisRequest(mode='ai'))
    assert report.status == 'committed' and not report.complete
    assert report.counts['coverage_gaps'] == 1
    assert 'fabricated-private-marker' not in str(store.rows('SELECT result FROM ai_analysis_units'))


def test_concurrent_manual_merge_is_not_erased_by_ai_publication(project, monkeypatch):
    import json

    from dataforge.analysis_service import run_analysis
    from dataforge.llm import merge_claims
    from dataforge.services import restore_manual_ai_results
    store, w = project
    analyze(store, w)
    source = store.file(store.files(w)[0]['file_id'])
    details = {'content_hash': source['content_hash'], 'job_id': 'workspace', 'result': {'claims': [{
        'source': 'raw.a', 'target': 'mart.x', 'operation': 'CREATE', 'start_line': 1, 'end_line': 1,
        'quote': source['raw_content'], 'explanation': 'Explicit source', 'confidence': .8}]}}
    store.execute('INSERT INTO llm_records(record_id,workspace_id,task,file_id,outcome,details) VALUES (?,?,?,?,?,?)',
                  ['manual', w, 'sql_lineage', source['file_id'], 'validated', json.dumps(details)])
    monkeypatch.setattr('dataforge.analysis_service.invoke_analysis_unit', fake_response)

    def merge_after_restoration(*args):
        restore_manual_ai_results(*args)
        merge_claims(store, w, 'manual')

    monkeypatch.setattr('dataforge.analysis_service.restore_manual_ai_results', merge_after_restoration)
    result = run_analysis(store, w, AnalysisRequest(mode='hybrid'))
    assert result.status == 'stale'
    assert any(edge['method'] == 'llm' for edge in store.edges(w))


def test_real_adapter_pipeline_counts_extraction_and_additional_review(project):
    import json

    import httpx

    from dataforge.ai_analysis_models import AnalysisUnit
    from dataforge.analysis_service import run_analysis
    store, w = project
    Importer(store, w).files([('q.sql',
        b'UPDATE mart.b SET total=a.x FROM raw.a a WHERE mart.b.id=a.id;')], {'.sql'})
    sent = []

    def respond(request):
        text = json.loads(request.content)['messages'][-1]['content']
        context = json.loads(text[text.index('{'):])
        unit = AnalysisUnit.model_validate(context['unit'])
        evidence = EvidenceCitation.from_unit(unit)
        sent.append(context)
        if 'candidates' in context:
            payload = {'decisions': [{'candidate_id': candidate['candidate_id'], 'decision': 'supported',
                'evidence': [evidence.model_dump()]} for candidate in context['candidates']]}
            usage = (20, 10)
        else:
            at = unit.start_offset + unit.code.index('a.x')
            payload = ProjectLineageResponse(unit_id=unit.unit_id, coverage=Coverage(status='complete'),
                derivations=[DerivationCandidate(target_table='mart.b', target_column='total', expression='a.x',
                    category='direct', inputs=[DerivationInput(table='raw.a', column='x'),
                        DerivationInput(table='mart.b', column='id', role='row_filter'),
                        DerivationInput(table='raw.a', column='id', role='row_filter')], evidence=evidence,
                    expression_start_offset=at, expression_end_offset=at + 3)]).model_dump()
            usage = (10, 5)
        return httpx.Response(200, json={'message': {'content': json.dumps(payload)},
            'done_reason': 'stop', 'prompt_eval_count': usage[0], 'eval_count': usage[1]})

    result = run_analysis(store, w, AnalysisRequest(mode='hybrid', additional_ai_review=True),
                          transport=httpx.MockTransport(respond))
    assert result.status == 'committed' and len(sent) == 2
    assert result.counts['requests'] == 2
    assert (result.counts['input_tokens'], result.counts['output_tokens']) == (30, 15)
    assert result.usage_known
    assert 'relationships' not in sent[0] and 'facts' not in sent[0]


def test_review_preview_reserves_compact_candidates_and_overflow_stays_unresolved(project, monkeypatch):
    from dataforge.ai_analysis_models import NormalizedFact
    from dataforge.ai_context import AIExecutionContext, plan_ai_units, prepare_analysis
    from dataforge.analysis_service import preview_analysis
    from dataforge.llm import REVIEW_CONTEXT_CHARS, analysis_prompt, review_payload
    store, w = project
    store.set_setting(w, 'max_context_chars', 8000)
    request = AnalysisRequest(mode='hybrid', additional_ai_review=True)
    plan = plan_ai_units(prepare_analysis(store, w, request))
    unit = plan.units[0]
    facts = [NormalizedFact(kind='derivation', unit_id=unit.unit_id, evidence_key='key',
        evidence=EvidenceCitation.from_unit(unit), candidate_id=str(i), table='mart.b', column=f'c{i}',
        expression=f'a.x{i}', inputs=[DerivationInput(table='raw.a', column=f'x{i}')]) for i in range(8)]
    compact, omitted = review_payload(facts)
    assert len(compact) == 8 and not omitted
    assert all('evidence' not in item and 'unit_id' not in item for item in compact)
    execution = AIExecutionContext(request)
    system, user, _ = analysis_prompt(unit, 'lineage_review', execution, reserve_review=True)
    assert len(system) + len(user) < 8000
    assert preview_analysis(store, w, request)['valid']
    facts[0].expression = 'x' * (REVIEW_CONTEXT_CHARS + 1)
    compact, omitted = review_payload(facts)
    assert '0' in omitted and len(compact) == 7


def test_eight_assignment_review_fits_default_context(project):
    import json

    import httpx

    from dataforge.ai_analysis_models import AnalysisUnit
    from dataforge.analysis_service import run_analysis
    store, w = project
    store.set_setting(w, 'max_context_chars', 8000)
    code = 'UPDATE mart.b SET ' + ','.join(f'c{i}=a.x{i}' for i in range(8)) + ' FROM raw.a a;'
    Importer(store, w).files([('q.sql', code.encode())], {'.sql'})
    sent = []

    def respond(request):
        text = json.loads(request.content)['messages'][-1]['content']
        ctx = json.loads(text[text.index('{'):])
        unit = AnalysisUnit.model_validate(ctx['unit'])
        evidence = EvidenceCitation.from_unit(unit)
        sent.append(ctx)
        if 'candidates' in ctx:
            payload = {'decisions': [{'candidate_id': c['candidate_id'], 'decision': 'supported',
                'evidence': [evidence.model_dump()]} for c in ctx['candidates']]}
        else:
            payload = ProjectLineageResponse(unit_id=unit.unit_id, coverage=Coverage(status='complete'),
                derivations=[DerivationCandidate(target_table='mart.b', target_column=f'c{i}',
                    expression=f'a.x{i}', category='direct', ordinal=i, inputs=[DerivationInput(table='raw.a', column=f'x{i}')],
                    evidence=evidence, expression_start_offset=unit.code.index(f'a.x{i}'),
                    expression_end_offset=unit.code.index(f'a.x{i}') + 4) for i in range(8)]).model_dump()
        return httpx.Response(200, json={'message': {'content': json.dumps(payload)}, 'done_reason': 'stop'})

    result = run_analysis(store, w, AnalysisRequest(mode='hybrid', additional_ai_review=True),
                          transport=httpx.MockTransport(respond))
    assert result.status == 'committed', result.reasons
    assert len(sent) == 2 and len(sent[1]['candidates']) == 8
