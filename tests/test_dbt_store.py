from contextlib import closing

from dataforge.models import AssetRef, Operation, ParseResult, Usage
from dataforge.store import Store


def test_resource_identity_survives_legacy_and_new_cache_payloads():
    result = ParseResult(operations=[Operation('SELECT', [AssetRef('same', identity='dbt:a')],
                         [AssetRef('same', identity='dbt:b')], 'select id', 1, 1,
                         usages=[Usage('same', 'id', table_identity='dbt:a')])])
    restored = ParseResult.from_dict(result.to_dict())
    assert restored.operations[0].sources[0].identity == 'dbt:a'
    assert restored.operations[0].usages[0].table_identity == 'dbt:a'
    old = result.to_dict()
    del old['operations'][0]['sources'][0]['identity']
    assert ParseResult.from_dict(old).operations[0].sources[0].identity == ''


def test_dbt_migration_reopens_without_erasing_legacy_data(tmp_path):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('existing')
        assert store.rows('SELECT max(version) AS v FROM schema_migrations')[0]['v'] == 9
        for table in ('dbt_projects', 'dbt_resources', 'dbt_relationships', 'dbt_evidence',
                      'dbt_relation_bindings', 'dbt_project_snapshots'):
            assert store.rows(f'SELECT count(*) AS n FROM {table}')[0]['n'] == 0
    with closing(Store(tmp_path)) as store:
        assert store.workspaces()[0]['workspace_id'] == workspace


def test_explicit_dbt_asset_identity_does_not_merge_same_names():
    from dataforge.asset_identity import AssetResolver
    from dataforge.configuration import ParsingSettings
    config = ParsingSettings().model_dump()
    result = ParseResult()
    resolver = AssetResolver('w', [], config)
    a, _ = resolver.resolve(AssetRef('same', identity='dbt:a'), {'relative_path': 'a.sql'}, result)
    b, _ = resolver.resolve(AssetRef('same', identity='dbt:b'), {'relative_path': 'a.sql'}, result)
    assert a != b
    assert resolver.registry[a][2] == resolver.registry[b][2] == 'same'
