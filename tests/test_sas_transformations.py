import pytest

from dataforge.parsers.sas import parse_sas


def physical(operation):
    return {d['target_column']: d for d in operation.derivations if not d['scope'] and d['target_column']}


def test_assignments_reference_the_previous_version_and_publish_latest_values():
    operation = parse_sas('data mart.x; set raw.orders; amount=quantity * price; amount=amount * 2; keep amount; run;').operations[0]
    steps = [d for d in operation.derivations if d['scope'] and d['target_column'] == 'amount']
    assert len(steps) == 2
    assert {(i['table'], i['column'], i['role']) for i in steps[0]['inputs']} == {
        ('raw.orders', 'quantity', 'value'), ('raw.orders', 'price', 'value')}
    assert steps[1]['inputs'] == [{'table': 'mart.x', 'column': 'amount', 'role': 'value',
                                   'scope': steps[0]['scope'], 'version': steps[0]['target_version']}]
    output = physical(operation)['amount']
    assert output['inputs'][0]['version'] == steps[1]['target_version']
    assert output['inputs'][0]['scope'] == steps[1]['scope']
    assert steps[0]['expression'] == 'amount=quantity * price;'
    assert steps[1]['expression'] == 'amount=amount * 2;'
    assert all(d['status'] == 'verified' for d in operation.derivations)


def test_literal_assignment_has_zero_inputs_without_an_invented_source():
    operation = parse_sas('data result; answer=42; label="raw.fake"; run;').operations[0]
    steps = [d for d in operation.derivations if d['scope']]
    assert {d['target_column'] for d in steps} == {'answer', 'label'}
    assert all(d['category'] == 'constant' and not d['inputs'] for d in steps)
    assert set(physical(operation)) == {'answer', 'label'}


def test_single_set_keep_rename_and_drop_preserve_physical_source_columns():
    operation = parse_sas('data published; set raw.orders(keep=id amount secret rename=(id=order_id)); '
                          'rename amount=total; drop secret; run;').operations[0]
    output = physical(operation)
    assert set(output) == {'order_id', 'total'}
    assert output['order_id']['inputs'][0]['column'] == 'id'
    assert output['total']['inputs'][0]['column'] == 'amount'
    assert not any(d['coverage'] for d in operation.derivations)


def test_drop_without_a_schema_keeps_unknown_passthrough_coverage_visible():
    operation = parse_sas('data published; set raw.orders; drop secret; total=amount * 2; run;').operations[0]
    assert set(physical(operation)) == {'total'}
    assert any(d['status'] == 'unresolved' and d['coverage'] for d in operation.derivations)


@pytest.mark.parametrize('body', ['merge raw.a raw.b; by id; x=id;', 'set raw.a; array v[2] a b; x=a;',
                                  'set raw.a; do i=1 to 2; x=i; end;', 'set raw.a; retain x; if id then x=1;'])
def test_procedural_constructs_have_explicit_unresolved_transformations(body):
    result = parse_sas('data mart.x; ' + body + ' run;')
    assert result.operations[0].derivations
    assert all(d['status'] == 'unresolved' for d in result.operations[0].derivations)
    assert any('transformation' in d.message.lower() for d in result.diagnostics)


def test_unknown_variable_without_set_is_unresolved_instead_of_a_constant():
    operation = parse_sas('data mart.x; amount=unknown * 2; run;').operations[0]
    assert physical(operation)['amount']['status'] == 'unresolved'


def test_proc_sql_remaps_work_and_libraries_for_targets_and_inputs():
    operation = parse_sas('proc sql; create table result as select id as order_id from src.orders; quit;',
                          library_mappings={'src': 'catalog.raw'}).operations[0]
    derivation = physical(operation)['order_id']
    assert derivation['target_table'] == 'work.result'
    assert {(i['table'], i['column']) for i in derivation['inputs'] if i['role'] == 'value'} == {
        ('catalog.raw.orders', 'id')}
    assert operation.method == 'sas-proc-sql'


def test_macro_expansion_never_substitutes_expression_evidence():
    result = parse_sas('%let multiplier=2; data mart.x; set raw.a; x=amount * &multiplier.; keep x; run;')
    operation = result.operations[0]
    step = next(d for d in operation.derivations if d['scope'])
    assert step['expression'] == 'x=amount * &multiplier.;'
    assert step['status'] == 'unresolved' and step['coverage']


def test_non_sql_procedure_reports_column_transformation_coverage():
    result = parse_sas('proc transpose data=raw.a out=mart.b; var amount; run;')
    assert any(d['status'] == 'unresolved' and d['coverage'] for d in result.operations[0].derivations)


def test_assignment_before_set_does_not_claim_a_value_read_from_the_next_row():
    result = parse_sas('data mart.x; x=amount * 2; set raw.orders; keep x; run;')
    assert result.operations[0].derivations
    assert all(d['status'] == 'unresolved' for d in result.operations[0].derivations)


def test_input_rename_changes_available_variable_names_before_assignments():
    operation = parse_sas('data mart.x; set raw.orders(rename=(id=order_id)); '
                          'old=id; new=order_id; keep old new; run;').operations[0]
    output = physical(operation)
    assert output['old']['status'] == 'unresolved'
    new = next(d for d in operation.derivations if d['scope'] and d['target_column'] == 'new')
    assert new['inputs'] == [{'table': 'raw.orders', 'column': 'id', 'role': 'value', 'scope': '', 'version': ''}]


def test_rename_without_keep_records_known_mapping_and_unknown_remaining_columns():
    operation = parse_sas('data mart.x; set raw.orders; rename id=order_id; run;').operations[0]
    assert physical(operation)['order_id']['inputs'][0]['column'] == 'id'
    assert any(d['target_column'] == '' and d['coverage'] for d in operation.derivations)


def test_macro_in_double_quoted_assignment_retains_original_text_and_uncertainty():
    operation = parse_sas('%let val=resolved; data mart.x; label="&val."; run;').operations[0]
    step = next(d for d in operation.derivations if d['scope'])
    assert step['expression'] == 'label="&val.";'
    assert step['status'] == 'unresolved'


def test_conflicting_output_rename_does_not_verify_two_values_for_one_column():
    operation = parse_sas('data mart.x; set raw.orders(keep=id order_id); rename id=order_id; run;').operations[0]
    assert all(d['status'] == 'unresolved' for d in operation.derivations if not d['scope'])


@pytest.mark.parametrize('expression', ['first.id', 'lag3(amount)', 'values{index}', '_n_'])
def test_runtime_or_qualified_variables_are_not_fabricated_as_input_columns(expression):
    operation = parse_sas(f'data mart.x; set raw.orders; x={expression}; keep x; run;').operations[0]
    assert physical(operation)['x']['status'] == 'unresolved'


@pytest.mark.parametrize('argument', ['amount', '1', '"literal"'])
def test_unknown_sas_function_is_unresolved_and_retains_known_argument_dependencies(argument):
    operation = parse_sas(f'data mart.x; set raw.orders; x=mystery({argument}); keep x; run;').operations[0]
    step = next(d for d in operation.derivations if d['scope'])
    assert step['status'] == 'unresolved' and step['category'] != 'constant'
    assert any('function' in reason.casefold() for reason in step['coverage'])
    assert {(i['table'], i['column']) for i in step['inputs']} == (
        {('raw.orders', 'amount')} if argument == 'amount' else set())
    assert physical(operation)['x']['status'] == 'unresolved'


@pytest.mark.parametrize('expression', ['sum(amount, tax)', 'coalesce(amount, 0)', 'abs(amount)',
                                       'round(amount, 0.01)', 'upcase(label)'])
def test_bounded_common_sas_function_assignments_preserve_verified_arguments(expression):
    operation = parse_sas(f'data mart.x; set raw.orders; x={expression}; keep x; run;').operations[0]
    assert physical(operation)['x']['status'] == 'verified'


def test_input_rename_cannot_verify_a_column_removed_by_input_keep():
    operation = parse_sas('data mart.x; set raw.orders(keep=order_id rename=(id=order_id)); '
                          'keep order_id; run;').operations[0]
    assert operation.derivations
    assert all(d['status'] == 'unresolved' for d in operation.derivations)
