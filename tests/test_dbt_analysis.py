from contextlib import closing

import pytest

from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.services import analyze, column_report
from dataforge.store import Store


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


def test_parser_upgrade_rebuilds_dbt_results_before_marking_current(tmp_path, monkeypatch):
    from dataforge.services import analysis_is_current

    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('dbt upgrade')
        Importer(store, w).files(fixture_entries(), set(), source_kind='dbt')
        analyze(store, w)
        assert analysis_is_current(store, w)
        monkeypatch.setattr('dataforge.services.PARSER_VERSION', 'future-parser')
        assert not analysis_is_current(store, w)
        rebuilt = analyze(store, w)
        assert rebuilt['analyzed'] == 6 and rebuilt['cached'] == 0
        assert analysis_is_current(store, w)


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
        Importer(store, w).files(fixture_entries('one') + fixture_entries('two'), set(), source_kind='dbt')
        analyze(store, w)
        matches = [a for a in store.assets(w) if a['name'] == 'stg_orders']
        assert len(matches) == 2
        refs = store.rows("SELECT DISTINCT asset_id FROM column_references WHERE table_name='stg_orders'")
        assert len(refs) == 2


def test_source_only_macro_and_unknown_branch_do_not_invent_reads(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('partial')
        entries = fixture_entries() + [('retail/models/dynamic.sql', b'''
{% if env_var('SECRET') %}select * from {{ ref('mart_orders') }}{% endif %}
''')]
        Importer(store, w).files(entries, set(), source_kind='dbt')
        analyze(store, w)
        assert len(store.edges(w)) == 3
        assert any('conditional' in d['message'].lower() for d in store.diagnostics(w))


def test_cancelled_dbt_analysis_retains_previous_graph(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace('cancel')
        Importer(store, w).files(fixture_entries(), set(), source_kind='dbt')
        analyze(store, w)
        with pytest.raises(InterruptedError):
            analyze(store, w, force=True, cancelled=lambda: True)
        assert len(store.edges(w)) == 3
