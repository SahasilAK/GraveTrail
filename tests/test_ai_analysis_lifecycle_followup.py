import json

import pytest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_republication_rebinds_committed_provenance_and_prunes_missing_facts(tmp_path):
    from dataforge.ai_analysis_store import (
        attach_published_support,
        refresh_published_support,
        save_claim_decisions,
        save_run,
    )
    from dataforge.services import prepare_analysis_results, publish_analysis_results
    store = Store(tmp_path)
    w = store.create_workspace('Support')
    Importer(store, w).files([('q.sql', b'CREATE TABLE b AS SELECT id FROM a;')], {'.sql'})
    results, config, counts = prepare_analysis_results(store, w)
    metadata, parsed = results[0]
    parsed.operations[0].evidence_key = 'host-key'
    publish_analysis_results(store, w, results, config, counts)
    claim = {'claim_id': 'claim', 'status': 'accepted', 'payload': {'kind': 'table_edge',
        'source': 'a', 'target': 'b', 'evidence_key': 'host-key', 'evidence': {'file_id': metadata['file_id']}}}
    save_run(store, w, 'ai-run', mode='ai', status='committed', configuration=config, accepted_results=results)
    save_claim_decisions(store, w, 'ai-run', [claim])
    assert attach_published_support(store, w, 'ai-run', results, [claim]) == 1
    store.execute('DELETE FROM analysis_fact_support')
    analyze(store, w)
    assert not store.rows('SELECT * FROM analysis_fact_support')  # Static publication replaces project AI support.
    store.execute('DELETE FROM edges')
    assert refresh_published_support(store, w, results) == 0
    assert not store.rows('SELECT * FROM analysis_fact_support')
    store.close()


def test_retention_strips_surviving_bodies_and_removes_only_unreferenced(tmp_path):
    from dataforge.ai_analysis_store import save_run, save_unit_result
    from dataforge.llm import expire_ai_history
    store = Store(tmp_path)
    w = store.create_workspace('Retention')
    for record_id, outcome in [('merged', 'merged'), ('unit', 'validated'), ('unused', 'quarantined')]:
        store.execute('''INSERT INTO llm_records(record_id,workspace_id,outcome,details,created_at)
            VALUES (?,?,?,?,current_timestamp - INTERVAL '40 days')''',
            [record_id, w, outcome, json.dumps({'context': 'private prompt', 'response': 'private response',
                                              'result': {'claims': []}, 'content_hash': 'source-hash'})])
    save_run(store, w, 'run', mode='hybrid', status='failed')
    save_unit_result(store, w, 'run', 'u', file_id='file', content_hash='hash', record_id='unit')
    expire_ai_history(store, w)
    rows = store.rows('SELECT record_id,details FROM llm_records')
    assert {r['record_id'] for r in rows} == {'merged', 'unit'}
    assert all('context' not in json.loads(r['details']) and 'response' not in json.loads(r['details']) for r in rows)
    assert all(json.loads(r['details'])['content_hash'] == 'source-hash' for r in rows)
    store.close()


@pytest.mark.parametrize('parallel', [False, True])
def test_agent_boundary_completeness_and_artifact_source_scope(tmp_path, parallel):
    from dataforge.agent.contracts import AccessPolicy
    from dataforge.agent.service import AgentService
    store = Store(tmp_path)
    w = store.create_workspace('Boundaries')
    Importer(store, w).files([('q.sql', b'CREATE TABLE b AS SELECT id FROM a;')], {'.sql'})
    analyze(store, w)
    edge = store.edges(w)[0]
    store.execute("UPDATE edges SET status='unresolved'")
    if parallel:
        columns = [d[0] for d in store.db.execute('SELECT * FROM edges LIMIT 0').description]
        row = store.rows('SELECT * FROM edges')[0] | {'edge_id': 'accepted', 'status': 'inferred'}
        store.execute('INSERT INTO edges VALUES (' + ','.join('?' for _ in columns) + ')', [row[k] for k in columns])
    service = AgentService(store, AccessPolicy(allow_write=True))
    try:
        for action, arguments in [('paths', {}), ('graph_view', {'view': 'edges'})]:
            result = service.call(action, w, asset='b', **arguments)
            assert result['complete'] is False and result['boundaries']
            assert edge['code'] not in json.dumps(result.get('unresolved_evidence', []))
        for kind in ('graph', 'impact', 'paths'):
            artifact = service.call('artifact_create', w, kind=kind, format='json',
                selection={'asset': 'a' if kind == 'impact' else 'b'})
            assert artifact['complete'] is False
            manifest = json.loads((store.home / 'agent' / 'artifacts' / w / (artifact['artifact_id'] + '.json')).read_text())
            assert edge['file_id'] in manifest['source_versions']
    finally:
        service.close()
        store.close()
