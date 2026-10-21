from contextlib import closing

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_custom_model_root_applies_disabled_folder_config(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('custom paths')
        Importer(store, w).files([('dbt_project.yml', b'name: shop\nmodel-paths: [src/models]\nmodels:\n  shop:\n    staging:\n      +enabled: false\n'),
            ('src/models/staging/base.sql', b'select 1 as id'),
            ('src/models/use.sql', b"select * from {{ ref('base') }}")], set(), source_kind='dbt')
        analyze(store, w)
        assert not next(r for r in store.rows('SELECT * FROM dbt_resources') if r['name'] == 'base')['enabled']
        assert not store.edges(w)


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


def test_seeds_yaml_snapshots_python_tests_and_exposures_have_typed_relationships(tmp_path):
    entries = [('dbt_project.yml', b'name: shop\n'), ('seeds/codes.csv', b'id,code\n1,A\n'),
        ('models/base.sql', b"select id, code from {{ ref('codes') }}"),
        ('models/py_model.py', b'def model(dbt, session):\n    return dbt.ref("base")\n'),
        ('models/properties.yml', b'''version: 2
models:
  - name: base
    data_tests: [unique]
    columns:
      - name: id
        data_tests: [not_null]
exposures:
  - name: sales_dashboard
    type: dashboard
    depends_on: ["ref('base')"]
semantic_models:
  - name: orders_semantics
    model: ref('base')
unit_tests:
  - name: test_base
    model: base
    given: []
    expect: {rows: []}
'''), ('snapshots/snapshots.yml', b"snapshots:\n  - name: code_history\n    relation: ref('base')\n    config: {strategy: timestamp, updated_at: updated_at}\n")]
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('resources')
        Importer(store, w).files(entries, set(), source_kind='dbt')
        analyze(store, w)
        resources = store.rows('SELECT * FROM dbt_resources')
        types = {r['resource_type'] for r in resources}
        assert {'seed', 'snapshot', 'model', 'test', 'unit_test', 'exposure', 'semantic_model'} <= types
        kinds = {r['kind'] for r in store.rows('SELECT * FROM dbt_relationships')}
        assert {'data_read', 'test_of', 'exposure_of', 'semantic_dependency'} <= kinds
        assets = {a['asset_id']: a['name'] for a in store.assets(w)}
        pairs = {(assets[e['source_id']], assets[e['target_id']]) for e in store.edges(w)}
        assert ('codes', 'base') in pairs
        assert ('base', 'py_model') in pairs
        assert ('base', 'code_history') in pairs
        assert not any('test' in name or 'dashboard' in name for pair in pairs for name in pair)


def test_versioned_models_resolve_latest_and_explicit_version(tmp_path):
    entries = [('dbt_project.yml', b'name: shop\n'),
        ('models/orders_v1.sql', b'select 1 as id'), ('models/orders_v2.sql', b'select 2 as id'),
        ('models/latest.sql', b"select id from {{ ref('orders') }}"),
        ('models/pinned.sql', b"select id from {{ ref('orders', v=1) }}"),
        ('models/properties.yml', b'models:\n  - name: orders\n    latest_version: 2\n    versions: [{v: 1}, {v: 2}]\n')]
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('versions')
        Importer(store, w).files(entries, set(), source_kind='dbt')
        analyze(store, w)
        resources = {r['resource_id']: r for r in store.rows('SELECT * FROM dbt_resources')}
        edges = store.rows("SELECT * FROM dbt_relationships WHERE kind='data_read'")
        assert {(resources[e['source_id']]['version'], resources[e['target_id']]['name']) for e in edges} == {
            ('1', 'pinned'), ('2', 'latest')}


def test_dbt_ai_is_rejected_before_context_disclosure(tmp_path):
    from dataforge.ai_context import prepare_analysis
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('AI guard')
        Importer(store, w).files([('dbt_project.yml', b'name: shop'),
            ('models/a.sql', b'select 1 as id')], set(), source_kind='dbt')
        import pytest
        with pytest.raises(ValueError, match='parser analysis'):
            prepare_analysis(store, w, {'mode': 'hybrid'})


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


def test_same_pair_with_conditional_support_does_not_fail_publication(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('Repeated')
        Importer(store, w).files([('dbt_project.yml', b'name: p'), ('models/base.sql', b'select 1 as id'),
            ('models/use.sql', b"select * from {{ ref('base') }} {% if target.name == 'prod' %} union all select * from {{ ref('base') }} {% endif %}")],
            set(), source_kind='dbt')
        analyze(store, w)
        assert len(store.edges(w)) == 1
