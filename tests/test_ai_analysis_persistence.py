import pytest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


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
