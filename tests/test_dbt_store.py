from contextlib import closing

from dataforge.store import Store


def test_dbt_migration_reopens_without_erasing_legacy_data(tmp_path):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('existing')
        assert store.rows('SELECT version FROM schema_migrations WHERE version=8')
        for table in ('dbt_projects', 'dbt_resources', 'dbt_relationships', 'dbt_evidence',
                      'dbt_relation_bindings', 'dbt_project_snapshots'):
            assert store.rows(f'SELECT count(*) AS n FROM {table}')[0]['n'] == 0
    with closing(Store(tmp_path)) as store:
        assert store.workspaces()[0]['workspace_id'] == workspace
