import json
from pathlib import Path

from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store
from dataforge.transformations import column_catalog, trace_columns


def test_sas_where_option_precedence_and_distinct_downstream_effects(tmp_path):
    code = b"""data mart.out;
    set raw.orders(where=(amount > 0));
    where ignored = 1;
    net=amount * 2;
    keep net;
    run;"""
    store = Store(tmp_path)
    try:
        w = store.create_workspace('SAS filtering')
        Importer(store, w).files([('filters.sas', code)], {'.sas'})
        analyze(store, w)
        assets = {a['name']: a['asset_id'] for a in store.assets(w)}
        upstream = trace_columns(store, w, assets['mart.out'], 'net')
        assert all(i['column_name'] != 'ignored' for d in upstream['derivations'] for i in d['inputs'])
        assert any(p['depth'] == 2 and p['parent_column_id'] != p['column_id'] for p in upstream['paths'])
        impact = trace_columns(store, w, assets['raw.orders'], 'amount', direction='downstream')
        target_id = upstream['derivations'][0]['target']['column_id']
        assert {p['effect'] for p in impact['paths'] if p['column_id'] == target_id} == {'value', 'row_selection'}
    finally:
        store.close()


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


def test_sas_append_and_update_publish_separate_value_and_membership_paths(tmp_path: Path) -> None:
    code = b"""data raw.base;
    input id amount base_only; datalines;
1 20 3
;
run;
data raw.incoming;
    input id amount risk_score; datalines;
1 10 4
;
run;
data mart.appended; set raw.base; run;
proc append base=mart.appended data=raw.incoming force; run;
data mart.updated; set raw.base; run;
proc sql;
update mart.updated set amount=amount*1.05
 where id in (select id from raw.incoming where risk_score>3);
update mart.unknown set amount=amount*1.05
 where id in (select id from raw.incoming where unknown.id=incoming.id);
update mart.unbound set amount=amount*1.05
 where id in (select id from raw.missing);
quit;"""
    store = Store(tmp_path)
    try:
        workspace = store.create_workspace('SAS in-place writes')
        Importer(store, workspace).files([('writes.sas', code)], {'.sas'})
        analyze(store, workspace)
        assets = {a['name']: a['asset_id'] for a in store.assets(workspace)}
        graph = LineageGraph(store.assets(workspace), store.edges(workspace)).graph
        for table, category in [('mart.appended', 'sas_append'), ('mart.updated', 'sas_update')]:
            assert set(graph.predecessors(assets[table])) == {assets['raw.base'], assets['raw.incoming']}
            trace = trace_columns(store, workspace, assets[table], 'amount', include_source=True)
            write = next(d for d in trace['derivations'] if d['category'] == category)
            assert write['evidence']['code'].encode() in code
            assert any(d['target']['table'] == 'raw.base' for d in trace['derivations'])
            assert any(c['reason'] == 'multiple_writers' for c in trace['coverage'])
            assert not any(c['reason'] == 'cycle' for c in trace['coverage'])
            assert {(i['table'], i['column_name']) for i in write['inputs'] if i['role'] == 'value'} == (
                {(table, 'amount'), ('raw.incoming', 'amount')} if category == 'sas_append'
                else {(table, 'amount')})
        assert {(i['table'], i['column_name'], i['role']) for i in write['inputs'] if i['role'] != 'value'} == {
            ('mart.updated', 'id', 'row_membership'), ('raw.incoming', 'id', 'row_membership'),
            ('raw.incoming', 'risk_score', 'row_filter')}
        assert trace_columns(store, workspace, assets['mart.appended'], 'risk_score')['state'] == 'no_known_dependency'
        assert trace_columns(store, workspace, assets['mart.unknown'], 'amount')['state'] == 'unresolved'
        unbound = trace_columns(store, workspace, assets['mart.unbound'], 'amount')
        assert unbound['state'] == 'unresolved'
        assert all(i['table'] != 'raw.missing' for d in unbound['derivations'] for i in d['inputs'])
    finally:
        store.close()


def test_sas_procedure_trace_keeps_known_columns_and_runtime_transpose_width(tmp_path: Path) -> None:
    code = b"""proc summary data=raw.orders nway;
    class customer_id;
    var amount risk_score;
    output out=mart.summary sum(amount)=total mean(risk_score)=risk_avg;
run;
proc transpose data=raw.orders out=mart.transposed prefix=AMT_;
    by customer_id;
    var amount risk_score;
run;
proc sql;
    create table mart.use_transpose as select AMT_2 as amount_2 from mart.transposed;
quit;
proc transpose data=raw.orders out=mart.declared prefix=AMT_;
    by customer_id;
    var amount risk_score;
run;
data mart.external;
    set raw.external;
run;"""
    store = Store(tmp_path)
    try:
        workspace = store.create_workspace('SAS procedure outputs')
        schema = b'create table mart.declared (customer_id int, _name_ varchar(32), AMT_1 int, AMT_2 int);'
        Importer(store, workspace).files([('procedures.sas', code), ('schema.sql', schema)], {'.sas', '.sql'})
        analyze(store, workspace)
        assets = {a['name']: a['asset_id'] for a in store.assets(workspace)}
        for name, source in [('total', 'amount'), ('risk_avg', 'risk_score')]:
            result = trace_columns(store, workspace, assets['mart.summary'], name)
            assert {(i['column_name'], i['role']) for i in result['derivations'][0]['inputs']} == {
                (source, 'value'), ('customer_id', 'value_selection'), ('', 'rowset')}
        transposed = assets['mart.transposed']
        assert trace_columns(store, workspace, transposed, 'customer_id')['state'] == 'known'
        for name in ('AMT_1', 'AMT_2'):
            numbered = trace_columns(store, workspace, transposed, name, include_source=True)
            step = numbered['derivations'][0]
            assert step['status'] == 'inferred' and step['target']['column_name'].upper() == name
            assert not numbered['complete'] and 'if present' in step['coverage'][0]
            assert {i['column_name'] for i in step['inputs'] if i['role'] == 'value'} == {'amount', 'risk_score'}
            assert step['evidence']['code'].encode() in code
        assert not trace_columns(store, workspace, transposed, 'AMT_0')['derivations']
        downstream = trace_columns(store, workspace, assets['mart.use_transpose'], 'amount_2')
        assert [d['target']['column_name'].upper() for d in downstream['derivations']][:2] == ['AMOUNT_2', 'AMT_2']
        impact = trace_columns(store, workspace, assets['raw.orders'], 'amount', direction='downstream')
        assert any(d['target']['column_name'] == 'amount_2' for d in impact['derivations'])
        declared = trace_columns(store, workspace, assets['mart.declared'], 'AMT_2')
        assert 'imported output schema' in declared['derivations'][0]['coverage'][0]
        assert not trace_columns(store, workspace, assets['mart.declared'], 'AMT_3')['derivations']
        wildcard = next(c for c in column_catalog(store, workspace, transposed) if c['column_name'] == '*')
        result = trace_columns(store, workspace, transposed, wildcard['column_id'])
        step = result['derivations'][0]
        assert step['status'] == 'unresolved' and 'AMT_' in step['coverage'][0]
        assert {(i['column_name'], i['role']) for i in step['inputs']} == {
            ('amount', 'value'), ('risk_score', 'value'), ('customer_id', 'value_selection')}
        external = trace_columns(store, workspace, assets['mart.external'], 'amount')
        assert external['state'] == 'unresolved'
        assert any('raw.external' in detail for c in external['coverage'] for detail in c.get('details', []))
    finally:
        store.close()


def test_sas_hash_and_fixed_array_steps_publish_value_origins(tmp_path: Path) -> None:
    code = b"""data raw.base;
    input id amount tax score; datalines;
1 10 2 5
;
run;
data raw.lookup;
    input id score; datalines;
1 9
;
run;
data mart.enriched;
    if _n_=1 then do;
        declare hash lookup(dataset:"raw.lookup");
        lookup.defineKey('id');
        lookup.defineData('score');
        lookup.defineDone();
    end;
    set raw.base;
    rc=lookup.find();
    if rc ne 0 then score=0;
    drop rc;
run;
data mart.rolled;
    set mart.enriched;
    retain total 0;
    array measures[2] amount tax;
    do idx=1 to dim(measures);
        measures[idx]=round(measures[idx],0.01);
    end;
    total+amount;
    prior=lag(amount);
    drop idx;
run;"""
    store = Store(tmp_path)
    try:
        workspace = store.create_workspace('SAS hash and array')
        Importer(store, workspace).files([('legacy.sas', code)], {'.sas'})
        analyze(store, workspace)
        assets = {a['name']: a['asset_id'] for a in store.assets(workspace)}
        graph = LineageGraph(store.assets(workspace), store.edges(workspace)).graph
        assert set(graph.predecessors(assets['mart.enriched'])) == {assets['raw.base'], assets['raw.lookup']}
        score = trace_columns(store, workspace, assets['mart.rolled'], 'score', depth=12)
        lookup = next(d for d in score['derivations'] if d['category'] == 'sas_hash_lookup')
        assert {(i['table'], i['column_name'], i['role']) for i in lookup['inputs']} == {
            ('raw.lookup', 'score', 'value'), ('raw.lookup', 'id', 'value_selection'),
            ('raw.base', 'id', 'value_selection')}
        for column, category in [('total', 'sas_retained_sum'), ('prior', 'sas_lag')]:
            trace = trace_columns(store, workspace, assets['mart.rolled'], column, depth=12, include_source=True)
            assert any(d['category'] == category for d in trace['derivations'])
            assert all(d['status'] != 'unresolved' for d in trace['derivations'])
            assert any(d['target']['table'] == 'raw.base' and d['target']['column_name'] == 'amount'
                       for d in trace['derivations'])
            assert all(i['column_name'] != 'tax' for d in trace['derivations'] for i in d['inputs'])
        assert trace_columns(store, workspace, assets['mart.rolled'], 'idx')['state'] == 'no_known_dependency'
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
