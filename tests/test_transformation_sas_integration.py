import json

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store
from dataforge.transformations import trace_columns


def test_sas_trace_preserves_ordered_variable_versions_and_original_source(tmp_path):
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


def test_sas_transformation_trace_isolates_same_temporary_label_between_jobs(tmp_path):
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


def test_proc_sql_transformation_trace_preserves_exact_projection_and_operation_evidence(tmp_path):
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
