"""Exact historical evidence resolution for the local column inspector."""

import json
from contextlib import closing

import pytest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def analyzed(tmp_path):
    with closing(Store(tmp_path / 'home')) as store:
        workspace = store.create_workspace('Evidence')
        Importer(store, workspace).files(
            [('job.sql', b'-- original\nCREATE TABLE dst AS SELECT a + 1 AS b FROM src;\n')], {'.sql'})
        analyze(store, workspace)
        derivation = store.rows('SELECT * FROM column_derivations WHERE workspace_id=?', [workspace])[0]
        yield store, workspace, derivation


def load(store, workspace, derivation, **kwargs):
    from dataforge.column_evidence import load_column_evidence

    return load_column_evidence(store, workspace, derivation['run_id'], derivation['derivation_id'], **kwargs)


def test_file_uses_exact_analyzed_hash_and_preserves_encoding(analyzed, monkeypatch):
    store, workspace, derivation = analyzed

    def forbidden(*args, **kwargs):
        pytest.fail('Original bytes are downloaded separately and lazily')

    monkeypatch.setattr(store, 'original', forbidden)
    before = load(store, workspace, derivation, include_file=True)
    assert before['state'] == 'available'
    assert before['file']['raw_content'].startswith('-- original\n')
    assert before['file']['encoding']
    assert before['file']['language'] == 'sql'
    assert before['file']['focus_start_line'] == before['evidence']['start_line']
    assert not before['file']['version_mismatch']
    Importer(store, workspace).files([('job.sql', b'SELECT changed FROM newest;')], {'.sql'})
    after = load(store, workspace, derivation, include_file=True)
    assert after['file']['raw_content'] == before['file']['raw_content']
    assert after['file']['content_hash'] == before['evidence']['source_hash']
    assert after['file']['version_mismatch']


def test_removed_exact_blob_never_falls_back_to_current(analyzed):
    store, workspace, derivation = analyzed
    digest = store.files(workspace)[0]['content_hash']
    Importer(store, workspace).files([('job.sql', b'SELECT newest FROM src;')], {'.sql'})
    (store.home / 'blobs' / digest).unlink()
    result = load(store, workspace, derivation, include_file=True)
    assert result['state'] == 'missing_version'
    assert result['file'] is None
    assert result['expression'] == 'a + 1 AS b'
    assert result['statement_preview']['code']


def test_corrupt_blob_is_not_presented_as_analyzed_source(analyzed):
    store, workspace, derivation = analyzed
    digest = store.files(workspace)[0]['content_hash']
    (store.home / 'blobs' / digest).write_bytes(b'tampered source')
    result = load(store, workspace, derivation, include_file=True)
    assert result['state'] == 'missing_version' and result['file'] is None


def test_old_selection_becomes_stale_after_reanalysis(analyzed):
    store, workspace, derivation = analyzed
    Importer(store, workspace).files([('job.sql', b'CREATE TABLE dst AS SELECT a + 2 AS b FROM src;')], {'.sql'})
    analyze(store, workspace)
    result = load(store, workspace, derivation, include_file=True)
    assert result['state'] == 'stale_run'
    assert result['expression'] == '' and result['evidence'] == {}
    assert result['file'] is None


def test_dbt_compiled_expression_never_focuses_original_or_manifest_coordinates(tmp_path):
    document = {'metadata': {'dbt_schema_version': 'https://schemas.getdbt.com/dbt/manifest/v12.json',
                'project_name': 'example', 'adapter_type': 'postgres'},
        'nodes': {'model.example.a': {'unique_id': 'model.example.a', 'resource_type': 'model',
            'name': 'a', 'package_name': 'example', 'original_file_path': 'models/a.sql',
            'config': {}, 'raw_code': 'select {{ 1 }} as a', 'compiled_code': 'select 1 as a',
            'depends_on': {'nodes': [], 'macros': []}}}, 'sources': {}, 'macros': {}}
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('dbt compiled')
        Importer(store, workspace).files([('manifest.json', json.dumps(document, indent=2).encode())], set(),
            source_kind='dbt', dbt_options={'mode': 'artifact', 'artifact_paths': ('manifest.json',)})
        analyze(store, workspace)
        derivation = store.rows('SELECT * FROM column_derivations')[0]
        result = load(store, workspace, derivation, include_file=True)
        assert result['expression'] == '1 as a'
        assert result['evidence']['origin'] == 'compiled_sql'
        assert not result['evidence']['focus_available']
        assert 'compiled' in result['evidence']['coordinate_warning'].lower()
        assert result['file']['focus_start_line'] is None
        assert result['file']['focus_end_line'] is None
        assert result['file']['language'] == 'json'
        assert result['statement_preview']['language'] == 'json'
