from typing import Any

from dataforge.parsers.csv import parse_csv
from dataforge.parsers.sas import parse_sas


def pairs(result: Any) -> Any:
    """Handle pairs for the test scenario.

    Args:
        result: Result produced by the operation.

    Returns:
        Value produced for the test scenario.
    """
    return {(s.name.lower(), t.name.lower()) for o in result.operations for s in o.sources for t in o.targets}


def test_csv_schema_never_executes_values() -> None:
    """Verify that csv schema never executes values."""
    r = parse_csv('id,name\n1,"create table bad as select * from secret"\n2,Ada\n', "input/x.csv")
    assert r.operations == []
    assert [c["name"] for c in r.metadata["columns"]] == ["id", "name"]
    assert r.metadata["row_count"] == 2
    assert r.assets[0].name == "file:input/x.csv"


def test_macro_control_flow_never_becomes_verified_unconditional_lineage() -> None:
    """Verify that macro control flow never becomes verified unconditional lineage."""
    r = parse_sas('''%if 0 %then %do;
data mart.false; set raw.source; run;
%end;
data mart.real; set raw.actual; run;''')
    assert pairs(r) == {("raw.actual", "mart.real")}
    assert r.diagnostics


def test_inline_data_is_never_parsed_as_code() -> None:
    """Verify that inline data is never parsed as code."""
    r = parse_sas('''data work.x; input line $80.; datalines;
data mart.fake; set raw.fake; run;
;
run;
data mart.actual; set raw.real; run;''')
    assert pairs(r) == {("raw.real", "mart.actual")}


def test_proc_sql_nested_formats_before_alias_and_comments_preserve_scope() -> None:
    """Verify that proc sql nested formats before alias and comments preserve scope."""
    statement = '''create table mart.x as select q.id format=8. as identifier
        from (select a.id /* format=bad from raw.fake */ format=best. as id
              from raw.a a) q;'''
    result = parse_sas('proc sql;\n' + statement + '\nquit;')
    assert not result.diagnostics
    assert pairs(result) == {('raw.a', 'mart.x')}
    assert {(u.table, u.column) for u in result.operations[0].usages} == {('raw.a', 'id')}
    assert result.operations[0].code == statement
