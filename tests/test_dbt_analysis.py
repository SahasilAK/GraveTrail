from contextlib import closing

import pytest

from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.services import analyze, column_report
from dataforge.store import Store
from dataforge.transformations import trace_columns


def fixture_entries(prefix='retail'):
    return [(f'{prefix}/dbt_project.yml', b'name: retail\n'),
        (f'{prefix}/models/sources.yml', b'''version: 2
sources:
  - name: raw
    schema: landing
    tables:
      - name: orders
        columns: [{name: id}, {name: amount}]
models:
  - name: stg_orders
    description: Staging orders
    columns: [{name: order_id}, {name: amount}]
'''),
        (f'{prefix}/models/stg_orders.sql', b"select id as order_id, amount from {{ source('raw', 'orders') }}\r\n"),
        (f'{prefix}/models/int_orders.sql', b"{{ config(materialized='ephemeral') }}\nselect order_id, amount * 2 as doubled from {{ ref('stg_orders') }}"),
        (f'{prefix}/models/mart_orders.sql', b"select order_id, doubled from {{ ref('int_orders') }}"),
        (f'{prefix}/macros/money.sql', b'{% macro money(x) %}{{ x }} / 100{% endmacro %}')]


def test_three_model_project_has_logical_outputs_and_original_evidence(tmp_path):
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace('dbt')
        Importer(store, workspace).files(fixture_entries(), set(), source_kind='dbt')
        result = analyze(store, workspace)
        graph = LineageGraph(store.assets(workspace), store.edges(workspace))
        pairs = {(graph.nodes[e['source_id']]['name'], graph.nodes[e['target_id']]['name'])
                 for e in store.edges(workspace)}
        assert pairs == {('raw.orders', 'stg_orders'), ('stg_orders', 'int_orders'), ('int_orders', 'mart_orders')}
        assert result['assets'] >= 4
        assert all(e['code'] and e['source_hash'] for e in store.edges(workspace))
        stg = next(a for a in store.assets(workspace) if a['name'] == 'stg_orders')
        assert {r['column_name'] for r in column_report(store, workspace, stg['asset_id'])} == {'order_id', 'amount'}
        assert store.rows('SELECT count(*) AS n FROM dbt_resources')[0]['n'] == 5
        again = analyze(store, workspace)
        assert again['analyzed'] == 0


def test_changed_macro_invalidates_unchanged_model_and_survives_cache_clear(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('dbt')
        imp = Importer(store, w)
        imp.files(fixture_entries(), set(), source_kind='dbt')
        analyze(store, w)
        before = store.rows('SELECT fingerprint FROM dbt_projects')[0]['fingerprint']
        entries = fixture_entries()
        entries[-1] = (entries[-1][0], b'{% macro money(x) %}{{ x }} / 1000{% endmacro %}')
        imp.files(entries, set(), source_kind='dbt')
        assert analyze(store, w)['analyzed'] > 0
        assert store.rows('SELECT fingerprint FROM dbt_projects')[0]['fingerprint'] != before
        store.execute('DELETE FROM parse_cache')
        assert analyze(store, w)['analyzed'] == 0
        assert len(store.edges(w)) == 3


def test_same_model_names_in_two_roots_keep_different_column_ids(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('two roots')
        entries = fixture_entries('one') + fixture_entries('two')
        entries = [(name, b"select * from {{ ref('stg_orders') }}" if name.endswith('/mart_orders.sql') else
                    b"select amount as other_amount from {{ source('raw', 'orders') }}" if
                    name == 'two/models/stg_orders.sql' else data) for name, data in entries]
        Importer(store, w).files(entries, set(), source_kind='dbt')
        analyze(store, w)
        matches = [a for a in store.assets(w) if a['name'] == 'stg_orders']
        assert len(matches) == 2
        refs = store.rows("SELECT DISTINCT asset_id FROM column_references WHERE table_name='stg_orders'")
        assert len(refs) == 2
        marts = [a['asset_id'] for a in store.assets(w) if a['name'] == 'mart_orders']
        for name in ('amount', 'other_amount'):
            traces = [trace_columns(store, w, aid, name) for aid in marts]
            known = [trace for trace in traces if trace['state'] == 'known']
            assert len(known) == 1
            assert {d['target']['table'] for d in known[0]['derivations']} == {'mart_orders', 'stg_orders'}


def test_source_only_macro_and_unknown_branch_do_not_invent_reads(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('partial')
        entries = fixture_entries() + [('retail/models/dynamic.sql', b'''
{% if env_var('SECRET') %}select * from {{ ref('mart_orders') }}{% endif %}
'''), ('retail/models/dynamic_args.sql', b"select * from {{ ref('mart_orders', **kwargs) }}")]
        Importer(store, w).files(entries, set(), source_kind='dbt')
        analyze(store, w)
        assert len(store.edges(w)) == 3
        assert any('conditional' in d['message'].lower() for d in store.diagnostics(w))


def test_dbt_databricks_stream_uses_shared_sql_bindings(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('Databricks dbt model')
        store.set_setting(w, 'dbt', {'dialect': 'databricks'})
        entries = [('retail/dbt_project.yml', b'name: retail\n'),
                   ('retail/seeds/feed.csv', b'id,amount\n1,5\n'),
                   ('retail/models/out.sql', b"""
with input as (select f.id, f.amount from STREAM({{ ref('feed') }}) as f)
select * from input
""")]
        Importer(store, w).files(entries, set(), source_kind='dbt')
        analyze(store, w)
        assets = {a['name']: a['asset_id'] for a in store.assets(w)}
        assert any(e['source_id'] == assets['feed'] and e['target_id'] == assets['out'] for e in store.edges(w))
        trace = trace_columns(store, w, assets['out'], 'amount')
        assert trace['state'] == 'known'
        assert any(i['table'] == 'file:retail/seeds/feed.csv' and i['column_name'] == 'amount'
                   for d in trace['derivations'] for i in d['inputs'])
        assert not trace_columns(store, w, assets['out'], 'unlisted')['derivations']


def test_opaque_aliased_projection_preserves_sibling_and_refuses_dynamic_relation(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('Partially static dbt models')
        entries = fixture_entries() + [
            ('retail/models/partial.sql', b"""
select order_id, {{ opaque('amount') }} as derived from {{ ref('stg_orders') }}
"""),
            ('retail/models/partial_star.sql', b"select * from {{ ref('partial') }}"),
            ('retail/models/dynamic_relation.sql', b"select q.id from {{ opaque('orders') }} as q"),
        ]
        Importer(store, w).files(entries, set(), source_kind='dbt')
        analyze(store, w)
        assets = {a['name']: a['asset_id'] for a in store.assets(w)}
        known = trace_columns(store, w, assets['partial'], 'order_id')
        assert [d['target']['table'] for d in known['derivations']] == ['partial', 'stg_orders']
        assert known['derivations'][0]['status'] == 'inferred'
        opaque = trace_columns(store, w, assets['partial'], 'derived')
        step = opaque['derivations'][0]
        assert step['status'] == 'unresolved' and not step['inputs']
        assert step['expression'] == "{{ opaque('amount') }} as derived"
        assert trace_columns(store, w, assets['partial_star'], 'order_id')['state'] == 'unresolved'
        assert not trace_columns(store, w, assets['dynamic_relation'], 'id')['derivations']
        assert not any(name.startswith('__gt_dbt_') for name in assets)


def test_dbt_implicit_qualifiers_and_unpinned_version_follow_logical_assets(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('Qualified and versioned dbt references')
        entries = [('retail/dbt_project.yml', b'name: retail\n'),
                   ('retail/models/properties.yml', b"""version: 2
sources:
  - name: raw
    tables: [{name: orders, identifier: landing_orders}]
models:
  - name: orders
    versions: [{v: 2}, {v: 10}]
"""),
                   ('retail/models/orders_v2.sql', b"select id as old_id from {{ source('raw', 'orders') }}"),
                   ('retail/models/orders_v10.sql', b"""{{ config(alias='latest_orders') }}
select landing_orders.id as order_id from {{ source('raw', 'orders') }}
"""),
                   ('retail/models/mart.sql', b"select latest_orders.order_id from {{ ref('orders') }}"),
                   ('retail/models/pinned.py', b'def model(dbt, session):\n    return dbt.ref("orders", version=2)\n')]
        Importer(store, w).files(entries, set(), source_kind='dbt')
        analyze(store, w)
        mart = next(a['asset_id'] for a in store.assets(w) if a['name'] == 'mart')
        trace = trace_columns(store, w, mart, 'order_id')
        assert [(d['target']['table'], d['target']['column_name']) for d in trace['derivations']] == [
            ('mart', 'order_id'), ('orders', 'order_id')]
        assert [(i['table'], i['column_name']) for i in trace['derivations'][-1]['inputs']] == [('raw.orders', 'id')]
        assert all(d['status'] == 'verified' for d in trace['derivations'])
        pinned = next(a['asset_id'] for a in store.assets(w) if a['name'] == 'pinned')
        assert trace_columns(store, w, pinned, 'old_id')['state'] == 'known'
        assert not trace_columns(store, w, pinned, 'order_id')['derivations']


def test_cancelled_dbt_analysis_retains_previous_graph(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('cancel')
        Importer(store, w).files(fixture_entries(), set(), source_kind='dbt')
        analyze(store, w)
        with pytest.raises(InterruptedError):
            analyze(store, w, force=True, cancelled=lambda: True)
        assert len(store.edges(w)) == 3
