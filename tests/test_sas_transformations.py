from typing import Any

from dataforge.parsers.sas import parse_sas


def test_summary_and_rank_keep_aggregate_inputs_separate_from_groups():
    parsed = parse_sas("""proc summary data=raw.a nway;
        class customer; var amount; output out=work.totals sum=total; run;
        proc rank data=work.totals out=mart.ranked groups=5; var total; ranks bucket; run;""")
    summary, rank = parsed.operations
    total = next(record for record in summary.derivations if record["target_column"] == "total")
    assert {(item["column"], item["role"]) for item in total["inputs"]} == {
        ("amount", "value"), ("customer", "value_selection"), ("", "rowset"),
    }
    bucket = next(record for record in rank.derivations if record["target_column"] == "bucket")
    assert {(item["column"], item["role"]) for item in bucket["inputs"]} == {
        ("total", "value"), ("", "rowset"),
    }


def physical(operation: Any) -> Any:
    """Handle physical for the test scenario.

    Args:
        operation: Operation value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    return {d['target_column']: d for d in operation.derivations if not d['scope'] and d['target_column']}


def test_drop_without_a_schema_keeps_unknown_passthrough_coverage_visible() -> None:
    """Verify that drop without a schema keeps unknown passthrough coverage visible."""
    operation = parse_sas('data published; set raw.orders; drop secret; total=amount * 2; run;').operations[0]
    assert set(physical(operation)) == {'total'}
    assert any(d['status'] == 'unresolved' and d['coverage'] for d in operation.derivations)


def test_procedural_constructs_have_explicit_unresolved_transformations() -> None:
    """Verify that procedural constructs have explicit unresolved transformations.

    Args:
        body: Body value used by the test case.
    """
    body = 'set raw.a; do i=1 to 2; x=i; end;'
    result = parse_sas('data mart.x; ' + body + ' run;')
    assert result.operations[0].derivations
    assert all(d['status'] == 'unresolved' for d in result.operations[0].derivations)
    assert any('transformation' in d.message.lower() for d in result.diagnostics)


def test_unknown_sas_function_is_unresolved_and_retains_known_argument_dependencies() -> None:
    """Verify that unknown sas function is unresolved and retains known argument dependencies.

    Args:
        argument: Argument value used by the test case.
    """
    argument = 'amount'
    operation = parse_sas(f'data mart.x; set raw.orders; x=mystery({argument}); keep x; run;').operations[0]
    step = next(d for d in operation.derivations if d['scope'])
    assert step['status'] == 'unresolved' and step['category'] != 'constant'
    assert any('function' in reason.casefold() for reason in step['coverage'])
    assert {(i['table'], i['column']) for i in step['inputs']} == {('raw.orders', 'amount')}
    assert physical(operation)['x']['status'] == 'unresolved'
