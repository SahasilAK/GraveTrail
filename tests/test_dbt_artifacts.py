import json
from contextlib import closing

import pytest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def manifest(compiled=True):
    return {'metadata': {'dbt_schema_version': 'https://schemas.getdbt.com/dbt/manifest/v12.json',
            'project_name': 'retail', 'adapter_type': 'postgres', 'invocation_id': 'run-a'},
        'nodes': {
            'model.retail.a': {'unique_id': 'model.retail.a', 'resource_type': 'model', 'name': 'a',
                'package_name': 'retail', 'original_file_path': 'models/a.sql', 'config': {'materialized': 'view'},
                'raw_code': "select id, {{ money('amount') }} as dollars from {{ source('raw', 'orders') }}",
                **({'compiled_code': 'select id, amount / 100 as dollars from landing.orders'} if compiled else {}),
                'depends_on': {'nodes': ['source.retail.raw.orders'], 'macros': ['macro.retail.money']},
                'database': 'db', 'schema': 'mart', 'alias': 'a'},
            'model.retail.b': {'unique_id': 'model.retail.b', 'resource_type': 'model', 'name': 'b',
                'package_name': 'retail', 'original_file_path': 'models/b.sql', 'config': {},
                'raw_code': "select id, dollars from {{ ref('a') }}",
                'depends_on': {'nodes': ['model.retail.a'], 'macros': []}}},
        'sources': {'source.retail.raw.orders': {'unique_id': 'source.retail.raw.orders',
            'resource_type': 'source', 'name': 'orders', 'source_name': 'raw', 'package_name': 'retail',
            'original_file_path': 'models/sources.yml', 'database': 'db', 'schema': 'landing',
            'identifier': 'orders', 'config': {}}},
        'macros': {'macro.retail.money': {'unique_id': 'macro.retail.money', 'name': 'money',
            'package_name': 'retail', 'resource_type': 'macro', 'original_file_path': 'macros/money.sql',
            'macro_sql': '{% macro money(x) %}{{ x }}/100{% endmacro %}', 'depends_on': {'macros': []}}}}


def test_settings_select_only_one_retained_manifest_and_auxiliary(tmp_path):
    from dataforge.dbt.models import DbtSettings
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('selection')
        entries = [('dbt_project.yml', b'name: retail'),
            ('dev/manifest.json', json.dumps(manifest()).encode()),
            ('prod/manifest.json', json.dumps(manifest()).encode()),
            ('dev/run_results.json', b'{"invalid": true}')]
        Importer(store, w).files(entries, set(), source_kind='dbt', dbt_options={
            'mode': 'enriched', 'artifact_paths': tuple(p for p, _ in entries[1:])})
        store.set_setting(w, 'dbt', DbtSettings(mode='enriched', artifact_paths=['prod/manifest.json']).model_dump())
        analyze(store, w)
        assert store.rows('SELECT count(*) AS n FROM dbt_resources')[0]['n'] == 4


def test_compiled_external_read_and_generated_evidence_are_preserved(tmp_path):
    data = manifest()
    node = data['nodes']['model.retail.a']
    node['compiled_code'] = 'select id from external.raw_orders'
    node['depends_on'] = {'nodes': [], 'macros': []}
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('external')
        Importer(store, w).files([('manifest.json', json.dumps(data).encode())], set(), source_kind='dbt',
            dbt_options={'mode': 'artifact', 'artifact_paths': ('manifest.json',)})
        analyze(store, w)
        assets = {a['asset_id']: a['name'] for a in store.assets(w)}
        assert ('external.raw_orders', 'a') in {(assets[e['source_id']], assets[e['target_id']]) for e in store.edges(w)}
        assert store.rows("SELECT * FROM dbt_evidence WHERE json_pointer='/nodes/model.retail.a/compiled_code' AND origin='compiled_sql'")


@pytest.mark.parametrize('compiled', [False, True])
def test_standalone_manifest_produces_dag_with_actual_json_evidence(tmp_path, compiled):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('artifact')
        raw = json.dumps(manifest(compiled), indent=2).encode()
        Importer(store, w).files([('target/manifest.json', raw)], set(), source_kind='dbt',
            dbt_options={'mode': 'artifact', 'artifact_paths': ('target/manifest.json',)})
        analyze(store, w)
        assets = {a['asset_id']: a['name'] for a in store.assets(w)}
        assert {(assets[e['source_id']], assets[e['target_id']]) for e in store.edges(w)} == {
            ('raw.orders', 'a'), ('a', 'b')}
        from dataforge.reporting import validate_lineage_evidence
        assert validate_lineage_evidence(store, w)['invalid_count'] == 0
        assert any(e['origin'] == 'artifact_declared' for e in store.rows('SELECT * FROM dbt_evidence'))
        if compiled:
            assert store.rows("SELECT * FROM column_derivations WHERE expression LIKE '%amount / 100%'")


def test_artifact_reader_rejects_unknown_schema_and_duplicate_keys():
    from dataforge.dbt.artifacts import read_artifact
    from dataforge.dbt.models import SourceRef
    source = SourceRef('id', 'hash', 'manifest.json')
    bad = manifest()
    bad['metadata']['dbt_schema_version'] = 'https://schemas.getdbt.com/dbt/manifest/v999.json'
    with pytest.raises(ValueError, match='schema'):
        read_artifact(source, json.dumps(bad))
    with pytest.raises(ValueError, match='Duplicate'):
        read_artifact(source, '{"metadata":{},"metadata":{}}')


def test_matching_catalog_and_results_enrich_observations_and_reject_other_invocation(tmp_path):
    from dataforge.dbt.artifacts import bind_artifacts, read_artifact
    from dataforge.dbt.models import SourceRef
    base = read_artifact(SourceRef('m', 'hash', 'manifest.json'), json.dumps(manifest()))
    catalog = {'metadata': {'dbt_schema_version': 'https://schemas.getdbt.com/dbt/catalog/v1.json'},
        'nodes': {'model.retail.a': {'metadata': {'database': 'db', 'schema': 'mart', 'name': 'a'},
                                   'columns': {'id': {'name': 'id', 'type': 'INTEGER', 'index': 1}}}}, 'sources': {}}
    results = {'metadata': {'dbt_schema_version': 'https://schemas.getdbt.com/dbt/run-results/v6.json', 'invocation_id': 'run-a'},
               'results': [{'unique_id': 'model.retail.a', 'status': 'success', 'execution_time': 0.5}]}
    docs = [base, read_artifact(SourceRef('c', 'hash', 'catalog.json'), json.dumps(catalog)),
            read_artifact(SourceRef('r', 'hash', 'run_results.json'), json.dumps(results))]
    observations = bind_artifacts(docs)
    assert observations['model.retail.a']['observed_columns']['id']['type'] == 'INTEGER'
    assert observations['model.retail.a']['observed_run']['status'] == 'success'
    results['metadata']['invocation_id'] = 'other-run'
    docs[-1] = read_artifact(SourceRef('r', 'hash', 'run_results.json'), json.dumps(results))
    with pytest.raises(ValueError, match='invocation'):
        bind_artifacts(docs)


def test_stale_manifest_rejects_publication_and_keeps_previous_graph(tmp_path):
    from dataforge.dbt.models import DbtSettings
    entries = [('dbt_project.yml', b'name: retail'),
        ('models/a.sql', b'select 1 as id'), ('target/manifest.json', json.dumps(manifest()).encode())]
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('stale')
        Importer(store, w).files(entries, set(), source_kind='dbt', dbt_options={'mode': 'enriched',
            'artifact_paths': ('target/manifest.json',)})
        store.set_setting(w, 'dbt', DbtSettings(mode='source').model_dump())
        analyze(store, w)
        before = store.assets(w)
        store.set_setting(w, 'dbt', DbtSettings(mode='enriched').model_dump())
        with pytest.raises(ValueError, match='source mismatch'):
            analyze(store, w)
        assert store.assets(w) == before
