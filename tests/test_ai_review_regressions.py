import httpx
from test_ai_resumable_files import configured, empty_provider
from test_ai_token_budget import model

from dataforge.ai_analysis_models import (
    AnalysisRequest,
    FileExtraction,
    OperationRecord,
    ResourceReference,
    SourceReference,
)
from dataforge.ai_linking import build_operation_graph, upstream_operations
from dataforge.analysis_service import preview_analysis, run_analysis
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_future_same_file_writer_cannot_become_an_upstream_producer():
    ref = SourceReference(file_id='f', content_hash='h', start_offset=0, end_offset=10)
    file = FileExtraction(file_id='f', content_hash='h', source_kind='sql', part_ids=['p'], operations=[
        OperationRecord(operation_id='early', kind='CREATE', evidence=[ref], order=0,
            reads=[ResourceReference(name='t')], writes=[ResourceReference(name='final')]),
        OperationRecord(operation_id='late', kind='CREATE', evidence=[ref], order=1,
            reads=[ResourceReference(name='external')], writes=[ResourceReference(name='t')])])
    graph = build_operation_graph([file])
    result = upstream_operations(graph, 'final')
    assert result.operation_ids == ['early']
    assert 'late' not in (result.execution_order or [])
    assert result.external_inputs


def test_planning_fits_the_final_pinned_metadata_and_relevant_context(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('pin fitting')
    configured(store, w, model(24000))
    Importer(store, w).files([('large.sql', ('select id from a;' + ' ' * 14000).encode()),
                              ('definition.sql', ('create table a(' + ','.join(f'c{i} int' for i in range(150)) + ');').encode())], {'.sql'})
    preview = preview_analysis(store, w, AnalysisRequest(mode='ai'))
    assert preview['valid'], preview['blocked']
    seen = []
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(empty_provider(seen)))
    assert result.status == 'committed', result.reasons
    assert len(set(seen)) >= 3
    store.close()


def test_selected_ai_rebuild_preserves_unselected_published_files(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('selected build')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'create table first as select id from raw.a;'),
                              ('b.sql', b'create table second as select id from raw.b;')], {'.sql'})
    analyze(store, w)
    selected = next(m['file_id'] for m in store.files(w) if m['relative_path'] == 'a.sql')
    result = run_analysis(store, w, AnalysisRequest(mode='ai', file_ids=[selected]),
                          transport=httpx.MockTransport(empty_provider([])))
    assert result.status == 'committed', result.reasons
    assert len(store.edges(w)) == 1
    assert {r['name'] for r in store.assets(w)} >= {'raw.b', 'second'}
    store.close()


def test_run_time_ceiling_survives_resume(tmp_path, monkeypatch):
    store = Store(tmp_path)
    w = store.create_workspace('time ceiling')
    configured(store, w)
    Importer(store, w).files([('a.sql', b'select 1;')], {'.sql'})
    clock, seen = [0.], []
    monkeypatch.setattr('dataforge.analysis_service.monotonic', lambda: clock[0], raising=False)
    normal = empty_provider(seen)
    def slow(request):
        clock[0] = 31.
        return normal(request)
    result = run_analysis(store, w, AnalysisRequest(mode='ai', max_seconds=30), transport=httpx.MockTransport(slow))
    assert result.status == 'awaiting_continuation'
    assert result.reasons == ['run_time_ceiling_reached']
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=result.run_id, retry_unknown=True),
                           transport=httpx.MockTransport(slow))
    assert resumed.reasons == ['run_time_ceiling_reached']
    assert len(seen) == 1
    store.close()


def test_scoped_same_named_inputs_keep_their_own_column_identity():
    from dataforge.ai_linking import link_file_extractions, to_publication_results
    ref = SourceReference(file_id='f', content_hash='h', start_offset=0, end_offset=10)
    file = FileExtraction(file_id='f', content_hash='h', source_kind='dbt', part_ids=['p'], operations=[
        OperationRecord(operation_id='op', kind='CREATE', evidence=[ref],
            reads=[ResourceReference(name='same', scope='pkg1', identity='one'), ResourceReference(name='same', scope='pkg2', identity='two')],
            writes=[ResourceReference(name='out')], derivations=[
                {'fact_id': scope, 'target_table': 'out', 'target_column': scope,
                 'inputs': [{'table': 'same', 'column': 'id', 'scope': scope}], 'evidence': [ref]}
                for scope in ('pkg1', 'pkg2')])])
    published = to_publication_results(link_file_extractions([file], {}), {'f': {'file_id': 'f', 'source_text': '0123456789'}})
    facts = published[0][1].operations[0].derivations
    assert facts[0]['inputs'][0]['table_identity'] == 'one'
    assert facts[1]['inputs'][0]['table_identity'] == 'two'


def test_consolidation_can_explicitly_replace_operation_fragments():
    from test_ai_file_parts import source

    from dataforge.ai_analysis_models import FilePart, PartExtraction
    from dataforge.ai_composition import assemble_file_extraction
    snapshot = source('select id from raw.a;')
    refs = [SourceReference(file_id='file', content_hash='hash', start_offset=a, end_offset=b) for a, b in ((0, 10), (10, len(snapshot.code)))]
    parts = [(FilePart(part_id=str(i), file_id='file', content_hash='hash', start_offset=r.start_offset,
        end_offset=r.end_offset, source_kind='sql', part_index=i), PartExtraction(part_id=str(i), operations=[
            OperationRecord(operation_id=str(i), kind='CREATE', evidence=[r], writes=[ResourceReference(name='out')])]))
        for i, r in enumerate(refs)]
    merged = PartExtraction(part_id='merge', superseded_operation_ids=['0', '1'], operations=[
        OperationRecord(operation_id='joined', kind='CREATE', evidence=refs, writes=[ResourceReference(name='out')])])
    final = assemble_file_extraction(snapshot, parts, [merged], provenance={})
    assert [o.operation_id for o in final.operations] == ['joined']
    assert not any(d.get('unresolved') for _, d in build_operation_graph([final]).nodes(data=True))


def test_unknown_completion_supersession_is_not_saved_as_completed(tmp_path, monkeypatch):
    import json

    from dataforge.ai_analysis_store import load_file_parts
    store = Store(tmp_path)
    w = store.create_workspace('supersession')
    configured(store, w)
    Importer(store, w).files([('consumer.sas', b'%load;'), ('definition.sas', b'opaque load;')], {'.sas'})
    poisoned = [True]
    stopped = [False]
    def stop(seconds, check):
        stopped[0] = True
        check()
    monkeypatch.setattr('dataforge.analysis_service.recovery_wait', stop)
    def provider(request):
        ctx = json.loads(json.loads(request.content)['messages'][-1]['content'])
        items = []
        for item in ctx['items']:
            part = item['part']
            ref = {k: part[k] for k in ('file_id', 'content_hash', 'start_offset', 'end_offset')}
            result = {'part_id': part['part_id']}
            if item['path'] == 'definition.sas':
                result['definitions'] = [{'entry_id': 'load', 'symbol': 'load', 'kind': 'macro', 'source_kind': 'sas',
                    'origin': 'ai_inferred', 'evidence': [ref]}]
            elif part['work_kind'] == 'extraction':
                result['missing_context'] = [{'symbol': 'load', 'kind': 'macro'}]
            elif poisoned[0]:
                result['superseded_fact_ids'] = ['bogus']
            items.append(result)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'items': items})}}]})
    first = run_analysis(store, w, AnalysisRequest(mode='ai'), cancelled=lambda: stopped[0], transport=httpx.MockTransport(provider))
    assert first.status == 'cancelled'
    initial = load_file_parts(store, w, first.run_id)
    assert len(initial) == 2 and all(p.work_kind == 'extraction' for p, _ in initial)
    assert any(r.definitions for _, r in initial)
    assert not store.rows('SELECT * FROM analysis_runs')
    poisoned[0] = False
    stopped[0] = False
    monkeypatch.setattr('dataforge.analysis_service.time', lambda: 1e12)
    resumed = run_analysis(store, w, AnalysisRequest(mode='ai', resume_run_id=first.run_id), transport=httpx.MockTransport(provider))
    assert resumed.status == 'committed', resumed.reasons
    assert all(record in load_file_parts(store, w, first.run_id) for record in initial)
    store.close()


def test_missing_credentials_block_preview_without_journaling_a_physical_attempt(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('credentials')
    from dataforge.model_capabilities import bind_capabilities
    profile = model().model_copy(update={'key_env': 'DATAFORGE_MISSING_REFAC_TEST_KEY'})
    profile.model_capabilities = bind_capabilities(profile.model_capabilities, profile)
    configured(store, w, profile)
    Importer(store, w).files([('a.sql', b'select 1;')], {'.sql'})
    preview = preview_analysis(store, w, AnalysisRequest(mode='ai'))
    assert not preview['valid']
    assert 'credential' in preview['blocked'][0]['reason']
    result = run_analysis(store, w, AnalysisRequest(mode='ai'), transport=httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(AssertionError('Disclosed source'))))
    assert result.status == 'blocked'
    assert not store.rows('SELECT * FROM ai_analysis_attempts')
    store.close()
