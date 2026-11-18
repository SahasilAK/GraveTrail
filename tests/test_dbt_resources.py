from contextlib import closing

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_source_column_tests_and_static_metric_dependencies(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('semantic')
        Importer(store, w).files([('dbt_project.yml', b'name: shop'), ('models/base.sql', b'select 1 as id'),
            ('models/properties.yml', b'''sources:
  - name: raw
    tables:
      - name: orders
        columns:
          - name: id
            data_tests: [unique, not_null]
semantic_models:
  - name: orders_semantics
    model: ref('base')
    measures: [{name: order_count, agg: count}]
metrics:
  - name: total_orders
    type: simple
    type_params: {measure: order_count}
saved_queries:
  - name: orders_report
    query_params: {metrics: [total_orders]}
''')], set(), source_kind='dbt')
        analyze(store, w)
        resources = {r['resource_id']: r for r in store.rows('SELECT * FROM dbt_resources')}
        links = {(resources[r['source_id']]['name'], resources[r['target_id']]['name'], r['kind'])
                 for r in store.rows('SELECT * FROM dbt_relationships')}
        assert ('orders_semantics', 'total_orders', 'semantic_dependency') in links
        assert ('total_orders', 'orders_report', 'semantic_dependency') in links
        tests = [r for r in resources.values() if r['resource_type'] == 'test']
        assert len(tests) == 2
        assert all(('raw.orders', r['name'], 'test_of') in links for r in tests)


def test_supplied_package_models_share_project_context_without_becoming_other_project(tmp_path):
    entries = [('dbt_project.yml', b'name: shop\npackages-install-path: vendor'),
        ('models/a.sql', b"select id from {{ ref('utils', 'base') }}"),
        ('vendor/utils/dbt_project.yml', b'name: utils'),
        ('vendor/utils/models/base.sql', b'select 1 as id')]
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('packages')
        Importer(store, w).files(entries, set(), source_kind='dbt', dbt_options={'include_packages': True})
        analyze(store, w)
        assert len(store.rows('SELECT * FROM dbt_projects')) == 1
        assert {r['package_name'] for r in store.rows('SELECT * FROM dbt_resources')} == {'shop', 'utils'}
        assert len(store.edges(w)) == 1


def test_manual_ai_preview_and_diagnostic_queue_exclude_dbt_sources(tmp_path):
    import pytest

    from dataforge.agent.contracts import AgentError
    from dataforge.ai_service import preview_ai_evidence
    from dataforge.assistance_queue import diagnostic_queue
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('no dbt AI')
        Importer(store, w).files([('dbt_project.yml', b'name: shop'),
            ('models/a.sql', b"select {{ missing_macro('id') }} as id")], set(), source_kind='dbt')
        analyze(store, w)
        fid = next(f['file_id'] for f in store.files(w) if f['extension'] == '.sql')
        with pytest.raises(AgentError):
            preview_ai_evidence(store, w, fid, 1, 1, 'sql_lineage')
        assert diagnostic_queue(store, w)['items'] == []


def test_duplicate_property_declarations_fail_without_replacing_committed_project(tmp_path):
    import pytest
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('duplicate')
        imp = Importer(store, w)
        entries = [('dbt_project.yml', b'name: shop'), ('models/a.sql', b'select 1 as id')]
        imp.files(entries, set(), source_kind='dbt')
        analyze(store, w)
        before = store.assets(w)
        imp.files([*entries, ('models/properties.yml', b'models: [{name: a}, {name: a}]')], set(), source_kind='dbt')
        with pytest.raises(ValueError, match='Duplicate'):
            analyze(store, w)
        assert store.assets(w) == before


def test_python_conditional_reference_is_not_a_proven_data_read(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('Python condition')
        Importer(store, w).files([('dbt_project.yml', b'name: p'), ('models/base.sql', b'select 1 as id'),
            ('models/use.py', b'def model(dbt, session):\n    if False:\n        return dbt.ref("base")\n    return None\n')],
            set(), source_kind='dbt')
        analyze(store, w)
        assert store.edges(w) == []
