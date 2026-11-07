import json
from pathlib import Path

from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store
from dataforge.transformations import trace_columns


def test_sas_match_merge_and_conditional_outputs_publish_column_trace(tmp_path: Path) -> None:
    code = """data raw.left;
    input id amount shared; datalines;
1 20 3
;
run;
data raw.right;
    input id amount shared; datalines;
1 10 4
;
run;
data work.combined;
    merge raw.left(in=in_left) raw.right(rename=(amount=other_amount));
    by id;
    if in_left;
    total=sum(amount,other_amount);
    drop other_amount;
run;
data mart.high mart.low mart.rest;
    set work.combined;
    if total > 20 then output mart.high;
    else if amount < 5 then output mart.low;
    else output mart.rest;
run;
data mart.final;
    set mart.high;
run;
data mart.unknown;
    merge raw.left raw.unknown;
    by id;
run;"""
    store = Store(tmp_path)
    try:
        workspace = store.create_workspace('SAS match merge and routing')
        Importer(store, workspace).files([('pipeline.sas', code.encode())], {'.sas'})
        analyze(store, workspace)
        assets = {a['name']: a['asset_id'] for a in store.assets(workspace)}
        graph = LineageGraph(store.assets(workspace), store.edges(workspace)).graph
        assert set(graph.predecessors(assets['work.combined'])) == {assets['raw.left'], assets['raw.right']}
        for table, conditions in [('mart.high', {'total'}), ('mart.low', {'total', 'amount'}),
                                  ('mart.rest', {'total', 'amount'})]:
            assert set(graph.predecessors(assets[table])) == {assets['work.combined']}
            trace = trace_columns(store, workspace, assets[table], 'total', depth=12, include_source=True)
            assert trace['state'] == 'known'
            assert all(d['status'] != 'unresolved' for d in trace['derivations'])
            route = trace['derivations'][0]
            assert {i['column_name'] for i in route['inputs'] if i['role'] == 'row_filter'} == conditions
            assert route['expression'] in code
            assert route['expression'].startswith('if total > 20 then output mart.high;')
            assert route['expression'].endswith(f'output {table};')
            assert {(i['table'], i['column_name']) for i in route['inputs'] if i['role'] == 'value'} == {
                ('work.combined', 'total')}
        trace = trace_columns(store, workspace, assets['mart.final'], 'total', depth=12)
        assert trace['state'] == 'known'
        assert all(d['status'] != 'unresolved' for d in trace['derivations'])
        merge_amounts = [d for d in trace['derivations'] if d['target']['column_name'] in {'amount', 'other_amount'}
                         and d['target']['scope']]
        assert {(d['target']['column_name'], i['table'], i['column_name'])
                for d in merge_amounts for i in d['inputs'] if i['role'] == 'value'} == {
            ('amount', 'raw.left', 'amount'), ('other_amount', 'raw.right', 'amount')}
        assert {(i['table'], i['column_name']) for d in merge_amounts for i in d['inputs'] if i['role'] == 'join'} == {
            ('raw.left', 'id'), ('raw.right', 'id')}
        shared = trace_columns(store, workspace, assets['work.combined'], 'shared')
        assert any('runtime' in gap for d in shared['derivations'] for gap in d['coverage'])
        assert {i['table'] for d in shared['derivations'] for i in d['inputs']
                if i['column_name'] == 'shared' and not i['scope']} == {'raw.left', 'raw.right'}
        assert trace_columns(store, workspace, assets['work.combined'], 'other_amount')['state'] != 'known'
        unknown = trace_columns(store, workspace, assets['mart.unknown'], 'amount')
        assert unknown['state'] != 'known'
        assert set(graph.predecessors(assets['mart.unknown'])) == {assets['raw.left'], assets['raw.unknown']}
    finally:
        store.close()


def test_sas_trace_preserves_ordered_variable_versions_and_original_source(tmp_path: Path) -> None:
    """Verify that sas trace preserves ordered variable versions and original source.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    code = ('data mart.x; set raw.orders; amount=quantity * price; '
            'amount=amount * 2; keep amount; run;')
    store = Store(tmp_path)
    try:
        workspace = store.create_workspace('SAS ordered assignments')
        Importer(store, workspace).files([('assign.sas', code.encode())], {'.sas'})
        analyze(store, workspace)
        asset = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 'mart.x')
        trace = trace_columns(store, workspace, asset, 'amount', depth=5, include_source=True)
        assert trace['state'] == 'known' and trace['complete']
        assert len(trace['derivations']) == 3
        physical, second, first = trace['derivations']
        assert physical['target']['scope'] == ''
        assert second['target']['version'] == '2' and first['target']['version'] == '1'
        assert physical['inputs'][0]['column_id'] == second['target']['column_id']
        assert second['inputs'][0]['column_id'] == first['target']['column_id']
        assert {(i['table'], i['column_name']) for i in first['inputs']} == {
            ('raw.orders', 'quantity'), ('raw.orders', 'price')}
        assert second['expression'] == 'amount=amount * 2;'
        assert all(d['evidence']['code'] == code and d['evidence']['method'] == 'sas-rules'
                   for d in trace['derivations'])
    finally:
        store.close()


def test_sas_transformation_trace_isolates_same_temporary_label_between_jobs(tmp_path: Path) -> None:
    """Verify that sas transformation trace isolates same temporary label between jobs.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    try:
        workspace = store.create_workspace('SAS job isolation')
        store.set_setting(workspace, 'job_by_folder', {'one/': 'one', 'two/': 'two'})
        Importer(store, workspace).files([
            ('one/stage.sas', b'data work.stage; set raw.a; amount=id * 2; keep amount; run;'),
            ('two/stage.sas', b'data work.stage; set raw.b; amount=id * 3; keep amount; run;')], {'.sas'})
        analyze(store, workspace)
        stages = [a for a in store.assets(workspace) if a['name'] == 'work.stage']
        assert len(stages) == 2
        for asset in stages:
            job = json.loads(asset['metadata'])['job_id']
            trace = trace_columns(store, workspace, asset['asset_id'], 'amount', depth=5)
            assert trace['complete']
            assert {d['evidence']['relative_path'] for d in trace['derivations']} == {f'{job}/stage.sas'}
            inputs = {i['table'] for d in trace['derivations'] for i in d['inputs'] if not i['scope']}
            assert inputs == {'raw.a' if job == 'one' else 'raw.b'}
    finally:
        store.close()


def test_proc_sql_transformation_trace_preserves_exact_projection_and_operation_evidence(tmp_path: Path) -> None:
    """Verify that proc sql transformation trace preserves exact projection and operation evidence.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    statement = ('create table mart.x as\n select o.quantity /* audited */ * o.price as amount '
                 'format=comma18.2\n from raw.orders o;')
    code = 'proc sql;\n' + statement + '\nquit;'
    store = Store(tmp_path)
    try:
        workspace = store.create_workspace('SAS PROC SQL evidence')
        Importer(store, workspace).files([('proc.sas', code.encode())], {'.sas'})
        analyze(store, workspace)
        asset = next(a['asset_id'] for a in store.assets(workspace) if a['name'] == 'mart.x')
        trace = trace_columns(store, workspace, asset, 'amount', include_source=True)
        step = trace['derivations'][0]
        assert step['expression'] == 'o.quantity /* audited */ * o.price as amount format=comma18.2'
        assert step['expression'] in code
        assert step['evidence']['code'] == statement
        assert (step['evidence']['start_line'], step['evidence']['end_line']) == (2, 4)
        assert step['evidence']['method'] == 'sas-proc-sql'
        assert {(i['table'], i['column_name']) for i in step['inputs'] if i['role'] == 'value'} == {
            ('raw.orders', 'quantity'), ('raw.orders', 'price')}
    finally:
        store.close()
