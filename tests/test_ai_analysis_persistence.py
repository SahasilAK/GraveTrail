import pytest

from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.models import AssetRef
from dataforge.services import analyze
from dataforge.store import Store


def test_unresolved_table_support_is_inspectable_boundary():
    nodes = [{'asset_id': n, 'name': n} for n in ['a', 'b', 'c']]
    edges = [{'source_id': s, 'target_id': t, 'edge_id': s+t, 'status': status}
             for s, t, status in [('a', 'b', 'verified'), ('b', 'c', 'unresolved')]]
    graph = LineageGraph(nodes, edges)
    assert not graph.graph.has_edge('b', 'c')
    assert graph.unresolved_edges == [edges[1]]
    report = graph.path_report('c')
    assert report['paths'][0]['boundary'] == 'unresolved'
    assert report['complete'] is False
    assert any(row['status'] == 'unresolved' for row in graph.lineage_rows())
    assert 'code' not in LineageGraph(nodes, [edges[1] | {'code': 'private source'}]).path_report('c')['boundaries'][0]
    accepted = edges[1] | {'edge_id': 'accepted', 'status': 'inferred'}
    parallel = LineageGraph(nodes, [*edges, accepted])
    assert parallel.path_report('c')['paths'][0]['nodes'] == ['a', 'b', 'c']
    assert parallel.graph['b']['c']['evidence'] == [accepted]


def test_prepare_sparse_publish_and_offline_rehydration(tmp_path):
    from dataforge.ai_analysis_store import load_accepted_file_results, save_run
    from dataforge.services import prepare_analysis_results, publish_analysis_results

    store = Store(tmp_path / 'home')
    w = store.create_workspace('Project')
    Importer(store, w).files([('a.sql', b'CREATE TABLE x AS SELECT id FROM a;')], {'.sql'})
    results, config, counts = prepare_analysis_results(store, w)
    assert store.assets(w) == []
    metadata, parsed = results[0]
    op = parsed.operations[0]
    op.method = 'ai-project'
    op.sources.append(AssetRef('b'))
    op.targets.append(AssetRef('y'))
    op.table_pairs = [(0, 0), (1, 1)]
    op.evidence_key = 'host-evidence'
    publish_analysis_results(store, w, results, config, counts)
    assert {(e['source_id'], e['target_id']) for e in store.edges(w)} == {
        (next(a['asset_id'] for a in store.assets(w) if a['name'] == source),
         next(a['asset_id'] for a in store.assets(w) if a['name'] == target))
        for source, target in [('a', 'x'), ('b', 'y')]}
    assert all(e['status'] == 'inferred' and e['confidence'] <= .8 for e in store.edges(w))
    assert {r['status'] for r in store.rows('SELECT status FROM column_derivations')} == {'inferred'}
    save_run(store, w, 'saved', mode='ai', status='committed', configuration=config, accepted_results=results)
    assert metadata['file_id'] in load_accepted_file_results(store, w, config)
    analyze(store, w)
    assert len(store.edges(w)) == 1  # Explicit Static selects static results.
    store.set_setting(w, 'case_sensitive', True)
    assert load_accepted_file_results(store, w, config | {'case_sensitive': True}) == {}
    store.close()


@pytest.mark.parametrize('direction,root', [('upstream', 'c'), ('downstream', 'a')])
def test_unresolved_column_derivation_stops_chaining(tmp_path, direction, root):
    from dataforge.transformations import trace_columns
    store = Store(tmp_path / 'home')
    w = store.create_workspace('Boundaries')
    Importer(store, w).files([('a.sql', b'CREATE TABLE b AS SELECT id FROM a; CREATE TABLE c AS SELECT id FROM b;')], {'.sql'})
    analyze(store, w)
    target = 'c' if direction == 'upstream' else 'b'
    store.execute('UPDATE column_derivations SET status=\'unresolved\' WHERE target_column_id IN (SELECT column_id FROM column_references WHERE table_name=?)', [target])
    aid = next(a['asset_id'] for a in store.assets(w) if a['name'] == root)
    report = trace_columns(store, w, aid, 'id', direction=direction)
    assert len(report['derivations']) == 1
    assert report['derivations'][0]['status'] == 'unresolved'
    assert not report['complete']
    store.close()


def test_checkpoints_provenance_guards_backup_and_recovery(tmp_path):
    from dataforge.ai_analysis_store import (
        load_analysis_report,
        recover_interrupted_runs,
        save_claim_decisions,
        save_run,
        save_unit_result,
    )
    from dataforge.cleanup import apply_cleanup, cleanup_plan
    from dataforge.database_maintenance import backup, inspect_database, restore_backup
    store = Store(tmp_path / 'home')
    w = store.create_workspace('Project')
    Importer(store, w).files([('a.sql', b'CREATE TABLE b AS SELECT id FROM a;')], {'.sql'})
    file = store.files(w)[0]
    save_run(store, w, 'run', mode='hybrid')
    save_unit_result(store, w, 'run', 'unit', file_id=file['file_id'], content_hash=file['content_hash'])
    save_claim_decisions(store, w, 'run', [{'claim_id': 'claim', 'unit_id': 'unit', 'kind': 'edge',
        'status': 'accepted', 'payload': {'source': 'a', 'target': 'b'}}],
        supports=[{'fact_type': 'edge', 'fact_id': 'edge', 'claim_id': 'claim', 'engine': 'ai'}])
    with pytest.raises(ValueError, match='active AI'):
        analyze(store, w)
    with pytest.raises(ValueError, match='active AI'):
        backup(store)
    recover_interrupted_runs(store)
    assert load_analysis_report(store, w)['status'] == 'interrupted'
    assert inspect_database(store)['ok']
    restore_backup(backup(store), tmp_path / 'restored')
    restored = Store(tmp_path / 'restored')
    assert load_analysis_report(restored, w)['claims'][0]['payload']['source'] == 'a'
    assert restored.rows('SELECT * FROM analysis_fact_support')
    restored.close()
    plan = cleanup_plan(store, w, 'ai')
    apply_cleanup(store, plan, 'Project')
    assert not store.rows('SELECT * FROM ai_analysis_runs')
    assert inspect_database(store)['ok']
    store.close()


def test_unselected_incompatible_accepted_facts_require_scope_reanalysis(tmp_path):
    from dataforge.ai_analysis_store import save_run
    from dataforge.services import prepare_analysis_results
    store = Store(tmp_path / 'home')
    w = store.create_workspace('Project')
    Importer(store, w).files([('a.sql', b'CREATE TABLE b AS SELECT id FROM a;'),
                              ('c.sql', b'CREATE TABLE d AS SELECT id FROM c;')], {'.sql'})
    results, config, _ = prepare_analysis_results(store, w)
    save_run(store, w, 'run', mode='ai', status='committed', configuration=config, accepted_results=results)
    store.set_setting(w, 'case_sensitive', True)
    with pytest.raises(ValueError, match='unselected'):
        prepare_analysis_results(store, w, [results[0][0]['file_id']])
    store.close()


def test_fact_support_rejects_foreign_claims_and_wrong_fact_types(tmp_path):
    from dataforge.ai_analysis_store import save_claim_decisions, save_run
    store = Store(tmp_path / 'home')
    w, other = store.create_workspace('one'), store.create_workspace('two')
    for workspace in (w, other):
        Importer(store, workspace).files([('a.sql', b'CREATE TABLE b AS SELECT id FROM a;')], {'.sql'})
        analyze(store, workspace)
        save_run(store, workspace, workspace, mode='hybrid', status='ready')
    save_claim_decisions(store, other, other, [{'claim_id': 'foreign', 'status': 'accepted'}])
    own = store.edges(w)[0]['edge_id']
    foreign = store.edges(other)[0]['edge_id']
    for support in [
        {'fact_type': 'edge', 'fact_id': own, 'claim_id': 'foreign'},
        {'fact_type': 'edge', 'fact_id': foreign},
        {'fact_type': 'derivation', 'fact_id': own},
        {'fact_type': 'unknown', 'fact_id': own},
    ]:
        with pytest.raises(ValueError):
            save_claim_decisions(store, w, w, [], supports=[support])
    store.close()


def test_boundary_exports_keep_incompleteness_and_original_support(tmp_path):
    import io
    import zipfile

    from dataforge.excel_exports import lineage_xlsx
    from dataforge.exports import graph_data, graph_html, path_rows
    from dataforge.reporting import workspace_health
    nodes = [{'asset_id': n, 'name': n, 'temporary': False} for n in ['a', 'b']]
    uncertain = {'source_id': 'a', 'target_id': 'b', 'edge_id': 'unresolved-edge', 'status': 'unresolved'}
    graph = LineageGraph(nodes, [uncertain, uncertain | {'edge_id': 'accepted', 'status': 'inferred'}])
    report = graph.path_report('b')
    assert all(row['report_complete'] is False for row in path_rows(report))
    assert graph_data(graph)['boundaries'] == [uncertain]
    assert graph_data(graph)['complete'] is False
    assert 'unresolved-edge' in graph_html(graph) and 'Unresolved evidence' in graph_html(graph)
    data, metadata = lineage_xlsx(report, graph.nodes, {'analysis_current': True})
    assert metadata['complete'] is False
    assert any('unresolved' in warning.lower() for warning in metadata['warnings'])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        texts = ''.join(archive.read(name).decode() for name in archive.namelist() if name.endswith('.xml'))
        assert 'Unresolved' in texts
    data, metadata = lineage_xlsx(report, graph.nodes, {'analysis_current': True}, include_evidence=True)
    assert metadata['evidence_count'] == 2
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        texts = ''.join(archive.read(name).decode() for name in archive.namelist() if name.endswith('.xml'))
        assert 'unresolved-edge' in texts
    store = Store(tmp_path / 'home')
    w = store.create_workspace('Empty')
    assert workspace_health(store, w, graph)['complete'] is False
    store.close()


def test_attach_published_support_uses_actual_typed_fact_ids(tmp_path):
    from dataforge.ai_analysis_store import attach_published_support, save_claim_decisions, save_run
    from dataforge.services import prepare_analysis_results, publish_analysis_results
    store = Store(tmp_path / 'home')
    w = store.create_workspace('Project')
    Importer(store, w).files([('a.sql', b'CREATE TABLE b AS SELECT id FROM a;')], {'.sql'})
    results, config, counts = prepare_analysis_results(store, w)
    metadata, parsed = results[0]
    op = parsed.operations[0]
    op.evidence_key = 'host-evidence'
    publish_analysis_results(store, w, results, config, counts)
    save_run(store, w, 'run', mode='hybrid', configuration=config, status='ready')
    common = {'evidence_key': op.evidence_key, 'evidence': {'file_id': metadata['file_id']}, 'origin': 'both'}
    payloads = [common | {'kind': 'table_edge', 'source': 'a', 'target': 'b'},
                common | {'kind': 'direct_usage', 'table': 'a', 'column': 'id', 'operation': 'SELECT'},
                common | {'kind': 'derivation', 'table': 'b', 'column': 'id', 'branch': 0, 'ordinal': 0,
                          'version': '', 'scope': '', 'expression': 'id'},
                common | {'kind': 'table_edge', 'source': 'invented', 'target': 'b'}]
    claims = [{'claim_id': str(i), 'status': 'accepted', 'payload': p} for i, p in enumerate(payloads)]
    save_claim_decisions(store, w, 'run', claims)
    attached = attach_published_support(store, w, 'run', results, claims)
    assert attached == 3
    support = store.rows('SELECT * FROM analysis_fact_support')
    assert {s['fact_type'] for s in support} == {'edge', 'usage', 'derivation'}
    for table, key, kind in [('edges', 'edge_id', 'edge'), ('column_usages', 'usage_id', 'usage'),
                              ('column_derivations', 'derivation_id', 'derivation')]:
        assert {s['fact_id'] for s in support if s['fact_type'] == kind} <= {
            row[key] for row in store.rows(f'SELECT {key} FROM {table}')}
    store.close()


def test_v5_upgrade_preserves_parser_manual_facts_and_originals(tmp_path):
    from dataforge.store import AI_ANALYSIS_TABLES
    store = Store(tmp_path / 'home')
    w = store.create_workspace('Existing')
    Importer(store, w).files([('a.sql', b'CREATE TABLE b AS SELECT id FROM a;')], {'.sql'})
    analyze(store, w)
    file = store.files(w)[0]
    edges = store.edges(w)
    store.execute("INSERT INTO llm_records(record_id,workspace_id,file_id,task,outcome,details) VALUES (?,?,?,?,?,?)",
                  ['manual', w, file['file_id'], 'sql_lineage', 'merged', '{}'])
    for table in AI_ANALYSIS_TABLES:
        store.execute(f'DROP TABLE {table}')
    store.execute('DELETE FROM schema_migrations WHERE version>=6')
    store.close()
    upgraded = Store(tmp_path / 'home')
    assert upgraded.edges(w) == edges
    assert upgraded.original(file['file_id']) == b'CREATE TABLE b AS SELECT id FROM a;'
    assert upgraded.rows("SELECT outcome FROM llm_records WHERE record_id='manual'") == [{'outcome': 'merged'}]
    assert all(upgraded.rows(f'SELECT count(*) AS n FROM {table}')[0]['n'] == 0 for table in AI_ANALYSIS_TABLES)
    upgraded.close()


def test_v7_file_snapshots_remove_aggregate_limit_and_preserve_legacy_read(tmp_path):
    from dataforge.ai_analysis_store import MAX_JSON_BYTES, load_accepted_file_results, save_run
    from dataforge.database_maintenance import inspect_database
    from dataforge.models import ParseResult
    store = Store(tmp_path)
    w = store.create_workspace('large accepted snapshot')
    Importer(store, w).files([(f'{i}.sql', b'select 1;') for i in range(3)], {'.sql'})
    results = [(m, ParseResult(metadata={'padding': 'x' * (6 * 1024 * 1024)})) for m in store.files(w)]
    with store.transaction():
        save_run(store, w, 'large', mode='hybrid', status='committed', configuration={}, accepted_results=results)
    rows = store.rows('SELECT payload FROM ai_analysis_snapshots')
    assert sum(len(row['payload']) for row in rows) > MAX_JSON_BYTES
    assert max(len(row['payload']) for row in rows) < MAX_JSON_BYTES
    assert len(load_accepted_file_results(store, w, {})) == 3
    assert inspect_database(store)['ok']
    assert store.rows("SELECT accepted_results FROM ai_analysis_runs WHERE run_id='large'")[0]['accepted_results'] == '[]'
    store.close()


def test_durable_final_claims_reference_source_instead_of_repeating_quotes(tmp_path, monkeypatch):
    from dataforge.ai_analysis_models import AnalysisRequest, EvidenceCitation
    from dataforge.ai_analysis_store import load_analysis_report, save_claim_decisions, save_run
    from dataforge.ai_context import plan_ai_units, prepare_analysis
    store = Store(tmp_path)
    w = store.create_workspace('compact final claims')
    code = 'select 1 /*' + 'x' * 50000 + '*/;'
    Importer(store, w).files([('q.sql', code.encode())], {'.sql'})
    unit = plan_ai_units(prepare_analysis(store, w, AnalysisRequest(mode='hybrid'))).units[0]
    save_run(store, w, 'r', mode='hybrid')
    payload = {'evidence': EvidenceCitation.from_unit(unit).model_dump(), 'kind': 'table_edge', 'source': 'a',
        'expression': code, 'detail': {'derivation': {'expression': code}}}
    save_claim_decisions(store, w, 'r', [{'claim_id': str(i), 'unit_id': unit.unit_id,
        'kind': 'table_edge', 'status': 'accepted', 'payload': payload} for i in range(100)])
    stored = store.rows('SELECT payload FROM ai_analysis_claims')
    assert max(len(row['payload']) for row in stored) < 1000
    original = store.snapshot_content
    reads = []
    def read_once(metadata):
        reads.append(metadata['content_hash'])
        return original(metadata)
    monkeypatch.setattr(store, 'snapshot_content', read_once)
    report = load_analysis_report(store, w, 'r')
    assert len(reads) == 1
    assert all(c['payload']['evidence']['quote'] == code for c in report['claims'])
    assert all(c['payload']['expression'] == code and c['payload']['detail']['derivation']['expression'] == code
        for c in report['claims'])
    assert payload['evidence']['quote'] == code
    store.close()


def test_large_expressions_reference_original_in_checkpoints_and_snapshots(tmp_path):
    from dataforge.ai_analysis_models import (
        AnalysisRequest,
        EvidenceCitation,
        NormalizedFact,
        ValidationReport,
    )
    from dataforge.ai_analysis_store import (
        load_accepted_file_results,
        load_validation_checkpoint,
        save_run,
        save_validation_checkpoint,
    )
    from dataforge.ai_context import plan_ai_units, prepare_analysis
    from dataforge.models import Operation, ParseResult
    store = Store(tmp_path)
    w = store.create_workspace('large original expression')
    expression = "'" + 'x' * (17 * 1024 * 1024) + "'"
    code = 'SELECT ' + expression + ' AS x;'
    Importer(store, w).files([('q.sql', code.encode())], {'.sql'})
    unit = plan_ai_units(prepare_analysis(store, w, AnalysisRequest(mode='ai')), adaptive=True).units[0]
    save_run(store, w, 'r', mode='ai')
    report = ValidationReport(accepted=[NormalizedFact(kind='derivation', unit_id=unit.unit_id, evidence_key='k',
        candidate_id='c', evidence=EvidenceCitation.from_unit(unit), expression=expression,
        detail={'derivation': {'expression': expression}})])
    save_validation_checkpoint(store, w, 'r', unit, 'h', report)
    stored = store.rows('SELECT payload FROM ai_analysis_claims')[0]['payload']
    assert len(stored) < 2000
    loaded = load_validation_checkpoint(store, w, 'r', unit, 'h')[0]
    assert loaded.accepted[0].expression == expression
    assert loaded.accepted[0].detail['derivation']['expression'] == expression
    metadata = store.files(w)[0]
    parsed = ParseResult(operations=[Operation(kind='SELECT', sources=[], targets=[], code=code, start=1, end=1,
        derivations=[{'expression': expression}])])
    save_run(store, w, 'r', mode='ai', status='committed', accepted_results=[(metadata, parsed)])
    assert max(len(r['payload']) for r in store.rows('SELECT payload FROM ai_analysis_snapshots')) < 2000
    assert load_accepted_file_results(store, w)[metadata['file_id']][1].operations[0].derivations[0]['expression'] == expression
    store.close()


def test_large_expression_provenance_survives_support_refresh(tmp_path):
    from dataforge.ai_analysis_models import AnalysisRequest, EvidenceCitation
    from dataforge.ai_analysis_store import (
        attach_published_support,
        refresh_published_support,
        save_claim_decisions,
        save_run,
    )
    from dataforge.ai_context import plan_ai_units, prepare_analysis
    from dataforge.services import prepare_analysis_results, publish_analysis_results
    store = Store(tmp_path)
    w = store.create_workspace('source reference support')
    code = "CREATE TABLE b AS SELECT '" + 'x' * 5000 + "' AS x;"
    Importer(store, w).files([('q.sql', code.encode())], {'.sql'})
    unit = plan_ai_units(prepare_analysis(store, w, AnalysisRequest(mode='ai'))).units[0]
    results, config, counts = prepare_analysis_results(store, w)
    op = results[0][1].operations[0]
    op.evidence_key = 'original'
    publish_analysis_results(store, w, results, config, counts)
    save_run(store, w, 'r', mode='ai', configuration=config, status='committed')
    payload = {'kind': 'derivation', 'table': 'b', 'column': 'x', 'evidence_key': op.evidence_key,
        'evidence': EvidenceCitation.from_unit(unit).model_dump(), 'expression': op.derivations[0]['expression']}
    claims = [{'claim_id': 'c', 'status': 'accepted', 'payload': payload}]
    save_claim_decisions(store, w, 'r', claims)
    assert attach_published_support(store, w, 'r', results, claims) == 1
    assert refresh_published_support(store, w, results) == 1
    assert len(store.rows('SELECT * FROM analysis_fact_support')) == 1
    store.close()
