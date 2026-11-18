import json

from dataforge.store import Store


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
