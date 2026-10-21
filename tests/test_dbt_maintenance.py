from contextlib import closing

from dataforge.database_maintenance import inspect_database
from dataforge.dbt.evidence import validate_dbt_evidence
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_dbt_catalog_and_original_evidence_survive_whole_home_restore(tmp_path):
    from dataforge.database_maintenance import backup, restore_backup
    with closing(Store(tmp_path / 'home')) as store:
        w = store.create_workspace('backup dbt')
        Importer(store, w).files([('dbt_project.yml', b'name: p'),
            ('models/a.sql', b'select 1 as id'),
            ('models/b.sql', b"select id from {{ ref('a') }}")], set(), source_kind='dbt')
        analyze(store, w)
        resources = store.rows('SELECT * FROM dbt_resources ORDER BY resource_id')
        archive = backup(store)
    restored = restore_backup(archive, tmp_path / 'restored')
    with closing(Store(restored)) as store:
        assert store.rows('SELECT * FROM dbt_resources ORDER BY resource_id') == resources
        assert len(store.edges(w)) == 1
        assert validate_dbt_evidence(store, w)['invalid_count'] == 0
        assert inspect_database(store)['ok']


def test_lineage_cleanup_preserves_dbt_import_classification(tmp_path):
    import json

    import pytest

    from dataforge.ai_context import prepare_analysis
    from dataforge.cleanup import apply_cleanup, cleanup_plan
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('cleanup dbt')
        Importer(store, w).files([('dbt_project.yml', b'name: shop'),
            ('models/a.sql', b'select 1 as id')], set(), source_kind='dbt')
        analyze(store, w)
        apply_cleanup(store, cleanup_plan(store, w, 'lineage'), 'cleanup dbt')
        assert all(json.loads(f['metadata'])['source_kind'] == 'dbt' for f in store.files(w))
        with pytest.raises(ValueError, match='parser analysis'):
            prepare_analysis(store, w, {'mode': 'hybrid'})
        analyze(store, w)
        assert len(store.rows('SELECT * FROM dbt_projects')) == 1


def test_dbt_integrity_and_historical_evidence_survive_reimport(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('dbt history')
        imp = Importer(store, w)
        entries = [('dbt_project.yml', b'name: shop'), ('models/a.sql', b'select 1 as id')]
        imp.files(entries, set(), source_kind='dbt')
        run = analyze(store, w)
        source = next(f for f in store.files(w) if f['extension'] == '.sql')
        imp.files([entries[0], ('models/a.sql', b'select 2 as id')], set(), source_kind='dbt')
        assert validate_dbt_evidence(store, w)['invalid_count'] == 0
        analyze(store, w)
        assert store.original(source['file_id'], source['content_hash']) == b'select 1 as id'
        assert inspect_database(store)['ok']
        assert store.rows('SELECT count(*) AS n FROM dbt_project_snapshots')[0]['n'] == 2
        assert store.rows('SELECT run_id FROM analysis_runs WHERE run_id=?', [run['run_id']])


def test_integrity_rejects_artifact_pointer_that_does_not_match_its_excerpt(tmp_path):
    import json
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('pointer')
        payload = {'metadata': {'dbt_schema_version': 'https://schemas.getdbt.com/dbt/manifest/v12.json', 'project_name': 'p'},
            'nodes': {'model.p.a': {'unique_id': 'model.p.a', 'resource_type': 'model', 'package_name': 'p',
                                  'name': 'a', 'config': {}}}}
        Importer(store, w).files([('manifest.json', json.dumps(payload).encode())], set(), source_kind='dbt',
            dbt_options={'mode': 'artifact', 'artifact_paths': ('manifest.json',)})
        analyze(store, w)
        store.execute("UPDATE dbt_evidence SET json_pointer='/nodes/missing'")
        assert validate_dbt_evidence(store, w)['invalid_count'] > 0
