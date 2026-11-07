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


def test_logic_is_bounded_and_never_loads_file_or_original(analyzed, monkeypatch):
    store, workspace, derivation = analyzed

    def forbidden(*args, **kwargs):
        pytest.fail('Logic-only inspection must not load full source')

    monkeypatch.setattr(store, 'file', forbidden)
    monkeypatch.setattr(store, 'original', forbidden)
    result = load(store, workspace, derivation)
    assert result['state'] == 'available'
    assert result['expression'] == 'a + 1 AS b'
    assert result['coverage'] == []
    assert result['statement_preview']['code'].endswith('SELECT a + 1 AS b FROM src;')
    assert result['statement_preview']['language'] == 'sql'
    assert not result['statement_preview']['truncated']
    assert 'file' not in result
    store.execute('UPDATE statements SET code=? WHERE statement_id=?', ['x' * 13000, derivation['statement_id']])
    result = load(store, workspace, derivation)
    assert len(result['statement_preview']['code']) == 12000
    assert result['statement_preview']['truncated']


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


@pytest.mark.parametrize('changed', [False, True])
def test_removed_exact_blob_never_falls_back_to_current(analyzed, changed):
    store, workspace, derivation = analyzed
    digest = store.files(workspace)[0]['content_hash']
    if changed:
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


def test_removed_inventory_file_keeps_logic_with_unavailable_source(analyzed):
    store, workspace, derivation = analyzed
    digest = store.files(workspace)[0]['content_hash']
    store.execute('DELETE FROM source_files WHERE file_id=?', [derivation['file_id']])
    result = load(store, workspace, derivation, include_file=True)
    assert result['state'] == 'missing_version' and result['file'] is None
    assert result['expression'] == 'a + 1 AS b'
    assert result['evidence']['source_hash'] == digest
    assert result['statement_preview']['code']


def test_old_selection_becomes_stale_after_reanalysis(analyzed):
    store, workspace, derivation = analyzed
    Importer(store, workspace).files([('job.sql', b'CREATE TABLE dst AS SELECT a + 2 AS b FROM src;')], {'.sql'})
    analyze(store, workspace)
    result = load(store, workspace, derivation, include_file=True)
    assert result['state'] == 'stale_run'
    assert result['expression'] == '' and result['evidence'] == {}
    assert result['file'] is None


@pytest.mark.parametrize('attack', ['workspace', 'derivation', 'run', 'statement_workspace', 'statement_file',
                                  'file_workspace', 'operation_statement'])
def test_invalid_membership_is_rejected(analyzed, attack):
    store, workspace, derivation = analyzed
    other = store.create_workspace('Other')
    if attack == 'workspace':
        workspace = other
    elif attack == 'derivation':
        derivation = {**derivation, 'derivation_id': 'forged'}
    elif attack == 'run':
        derivation = {**derivation, 'run_id': 'forged'}
    elif attack == 'statement_workspace':
        store.execute('UPDATE statements SET workspace_id=? WHERE statement_id=?', [other, derivation['statement_id']])
    elif attack == 'statement_file':
        store.execute('UPDATE statements SET file_id=? WHERE statement_id=?', ['forged', derivation['statement_id']])
    elif attack == 'file_workspace':
        store.execute('UPDATE source_files SET workspace_id=? WHERE file_id=?', [other, derivation['file_id']])
    else:
        store.execute('UPDATE operations SET statement_id=? WHERE operation_id=?', ['forged', derivation['operation_id']])
    with pytest.raises(ValueError):
        load(store, workspace, derivation, include_file=True)


def test_unknown_workspace_is_rejected(analyzed):
    store, _, derivation = analyzed
    with pytest.raises(ValueError):
        load(store, 'forged-workspace', derivation)


def test_sas_language_and_original_line_focus(tmp_path):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('SAS')
        Importer(store, workspace).files([('job.sas', b'data dst; set src; b=a+1; run;')], {'.sas'})
        analyze(store, workspace)
        derivation = store.rows("SELECT * FROM column_derivations WHERE expression LIKE '%a+1%'")[0]
        result = load(store, workspace, derivation, include_file=True)
        assert result['statement_preview']['language'] == 'sas'
        assert result['file']['language'] == 'sas'
        assert result['evidence']['origin'] == 'original'
        assert result['evidence']['focus_available']


def test_dbt_original_source_keeps_template_coordinates(tmp_path):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('dbt source')
        Importer(store, workspace).files([('dbt_project.yml', b'name: example\n'),
            ('models/a.sql', b'-- template\nselect 1 as a\n')], set(), source_kind='dbt')
        analyze(store, workspace)
        derivation = store.rows('SELECT * FROM column_derivations')[0]
        result = load(store, workspace, derivation, include_file=True)
        assert result['evidence']['origin'] == 'original'
        assert result['evidence']['focus_available']
        assert result['file']['raw_content'].startswith('-- template\n')


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
