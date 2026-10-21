import io
import zipfile
from contextlib import closing

import pytest

from dataforge.ingestion import Importer
from dataforge.store import Store


def project_entries():
    return [
        ('retail/dbt_project.yml', b'name: retail\nmodel-paths: [queries]\n'),
        ('retail/queries/orders.sql', b"select * from {{ source('raw', 'orders') }}\r\n"),
        ('retail/queries/schema.yaml', b'version: 2\nmodels: [{name: orders}]\n'),
        ('retail/macros/money.sql', b'{% macro money(x) %}{{ x }}{% endmacro %}'),
        ('retail/profiles.yml', b'password: private'),
        ('retail/.env', b'SECRET=private'),
        ('retail/target/manifest.json', b'{}'),
        ('retail/unrelated.py', b'raise Exception()'),
        ('retail/unrelated.csv', b'private\n1'),
    ]


def test_failed_dbt_replacement_preserves_complete_previous_inventory(tmp_path):
    from dataforge.ingestion import Limits
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('atomic')
        importer = Importer(store, workspace)
        importer.files([('dbt_project.yml', b'name: p'), ('models/a.sql', b'select 1 as id'),
                        ('models/b.sql', b'select 2 as id')], set(), source_kind='dbt')
        before = store.files(workspace)
        importer.limits = Limits(max_file_bytes=32)
        with pytest.raises(ValueError, match='size limit'):
            importer.files([('dbt_project.yml', b'name: p'), ('models/a.sql', b'select 3 as id'),
                            ('models/b.sql', b' ' * 64)], set(), source_kind='dbt')
        assert store.files(workspace) == before


@pytest.mark.parametrize('kind', ['files', 'zip', 'directory'])
def test_dbt_import_preserves_paths_and_original_bytes(tmp_path, kind):
    entries = project_entries()
    with closing(Store(tmp_path / 'home')) as store:
        workspace = store.create_workspace('dbt')
        importer = Importer(store, workspace, [tmp_path])
        if kind == 'files':
            report = importer.files(entries, set(), source_kind='dbt')
        elif kind == 'zip':
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                for path, data in entries:
                    archive.writestr(path, data)
            report = importer.zip(stream.getvalue(), set(), source_kind='dbt')
        else:
            folder = tmp_path / 'input'
            for path, data in entries:
                target = folder / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            report = importer.directory(folder, set(), source_kind='dbt')
        assert report.accepted == 4
        assert {f['relative_path'] for f in store.files(workspace)} == {p for p, _ in entries[:4]}
        source = next(f for f in store.files(workspace) if f['relative_path'].endswith('/orders.sql'))
        assert store.original(source['file_id']) == entries[1][1]


def test_profiles_env_logs_and_unselected_target_never_read():
    from dataforge.dbt.imports import DbtImportOptions, preview_dbt_import
    entries = [p for p, _ in project_entries()] + ['retail/logs/private.sql']
    reads = []

    def read(path):
        reads.append(path)
        assert path == 'retail/dbt_project.yml'
        return 'name: retail\nmodel-paths: [queries]\n'

    plan = preview_dbt_import(entries, DbtImportOptions(), read)
    assert reads == ['retail/dbt_project.yml']
    assert set(plan.paths) == set(entries[:4])


@pytest.mark.parametrize('text', [
    'name: a\nmodel-paths: [../private]',
    'name: a\nmodel-paths: [/private]',
    'name: a\nmodel-paths: ["{{ env_var(\'PRIVATE\') }}"]',
    'name: a\nname: b',
    'name: !!python/object/apply:os.system [echo nope]',
    'name: a\nx: &x [*x]',
])
def test_dbt_project_configuration_rejects_unsafe_yaml_and_paths(text):
    from dataforge.dbt.yaml import read_project_paths
    with pytest.raises(ValueError):
        read_project_paths(text)


def test_dbt_case_colliding_paths_rejected_before_any_read():
    from dataforge.dbt.imports import DbtImportOptions, preview_dbt_import
    with pytest.raises(ValueError, match='collision'):
        preview_dbt_import(['dbt_project.yml', 'models/A.sql', 'models/a.sql'], DbtImportOptions(),
                           lambda _: pytest.fail('collision must be rejected before source read'))
