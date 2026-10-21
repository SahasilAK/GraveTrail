from typing import Any

import pytest

from dataforge.parsers.csv import parse_csv
from dataforge.parsers.sas import parse_sas


def test_sas_blocks_preserve_original_spacing_comments_and_same_line_boundaries() -> None:
    """Verify that sas blocks preserve original spacing comments and same line boundaries."""
    first = "data work.stage;   set raw.a;\n\n  /* retained comment */ keep id; run;"
    second = "data mart.x; set work.stage; run;"
    code = "\n  " + first + "   " + second + "\n"
    result = parse_sas(code)
    assert [operation.code for operation in result.operations] == [first, second]
    assert result.operations[0].start == 2 and result.operations[0].end == 4
    assert result.operations[1].start == 4 and result.operations[1].end == 4
    assert all(operation.code in code for operation in result.operations)


def test_sas_proc_evidence_is_an_original_contiguous_block() -> None:
    """Verify that sas proc evidence is an original contiguous block."""
    code = "proc sort data=raw.a out=mart.x;   by id;\n\nrun;"
    result = parse_sas(code)
    assert result.operations[0].code == code


def test_sas_evidence_offsets_skip_identical_tokens_inside_inline_data() -> None:
    """Verify that sas evidence offsets skip identical tokens inside inline data."""
    code = "data work.inline;\ninput text $;\ndatalines;\nrun;\n;\nrun;"
    result = parse_sas(code)
    assert result.operations[0].code == code
    assert result.operations[0].end == 6


def pairs(result: Any) -> Any:
    """Handle pairs for the test scenario.

    Args:
        result: Result produced by the operation.

    Returns:
        Value produced for the test scenario.
    """
    return {(s.name.lower(), t.name.lower()) for o in result.operations for s in o.sources for t in o.targets}


def test_csv_work_staging_proc_sql_and_columns() -> None:
    """Verify that csv work staging proc sql and columns."""
    code = '''proc import datafile="input/customers.csv" out=work.customers_stage dbms=csv replace;
run;
data staging.customers;
set work.customers_stage(keep=customer_id customer_name);
keep customer_id customer_name;
run;
proc sql;
create table mart.summary as select customer_id,count(*) as n from staging.customers group by customer_id;
quit;'''
    r = parse_sas(code)
    assert pairs(r) == {("file:input/customers.csv", "work.customers_stage"),
                        ("work.customers_stage", "staging.customers"), ("staging.customers", "mart.summary")}
    assert r.operations[0].targets[0].temporary
    assert any(u.column == "customer_id" for u in r.operations[1].usages)
    assert r.operations[2].start == 8


def test_static_macros_libraries_and_ambiguous_macro() -> None:
    """Verify that static macros libraries and ambiguous macro."""
    r = parse_sas('''%let src=raw;
data mart.x; set &src..orders; run;
data mart.y; set &unknown..orders; run;
%macro risky(); data mart.fake; set raw.fake; run; %mend;
%risky();''', library_mappings={"raw": "catalog.raw"})
    assert pairs(r) == {("catalog.raw.orders", "mart.x")}
    assert any("unknown" in d.message.lower() for d in r.diagnostics)
    assert not any("fake" in s for p in pairs(r) for s in p)


def test_common_procedures_and_data_merge() -> None:
    """Verify that common procedures and data merge."""
    r = parse_sas('''data mart.joined; merge raw.a raw.b; by id; run;
proc sort data=mart.joined out=work.sorted; by id; run;
proc means data=work.sorted; output out=mart.stats; run;
proc transpose data=mart.stats out=mart.wide; run;
proc export data=mart.wide outfile="output/wide.csv" dbms=csv; run;''')
    assert pairs(r) == {("raw.a", "mart.joined"), ("raw.b", "mart.joined"),
                        ("mart.joined", "work.sorted"), ("work.sorted", "mart.stats"),
                        ("mart.stats", "mart.wide"), ("mart.wide", "file:output/wide.csv")}
    assert not any(u.table in {"raw.a", "raw.b"} for u in r.operations[0].usages)


def test_comments_and_literals_do_not_generate_phantom_edges() -> None:
    """Verify that comments and literals do not generate phantom edges."""
    r = parse_sas('''/* data fake; set phantom; run; */
data mart.x; set raw.real; value="set raw.fake;"; run;
* data fake2; set raw.other; run;''')
    assert ("raw.fake", "mart.x") not in pairs(r)
    assert ("raw.real", "mart.x") in pairs(r)


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


def test_name_literals_are_unresolved_instead_of_scanned_as_plain_identifiers() -> None:
    """Verify that name literals are unresolved instead of scanned as plain identifiers."""
    r = parse_sas("data mart.x; set 'raw.orders'n; run;")
    assert pairs(r) == set()
    assert r.diagnostics


def test_inline_data_is_never_parsed_as_code() -> None:
    """Verify that inline data is never parsed as code."""
    r = parse_sas('''data work.x; input line $80.; datalines;
data mart.fake; set raw.fake; run;
;
run;
data mart.actual; set raw.real; run;''')
    assert pairs(r) == {("raw.real", "mart.actual")}


def test_csv_extreme_width_and_header_errors_are_diagnostics() -> None:
    """Verify that csv extreme width and header errors are diagnostics."""
    r = parse_csv("," * 20000 + "\n", "wide.csv")
    assert r.diagnostics and len(r.metadata.get("columns", [])) <= 4096
    r = parse_csv("a" * 140000 + "\n1\n", "long.csv")
    assert any(d.severity == "error" for d in r.diagnostics)
    r = parse_csv('unquoted"' + "," * 20000 + "\n", "quote_bypass.csv")
    assert r.diagnostics and len(r.metadata.get("columns", [])) <= 4096


@pytest.mark.parametrize('attribute', ['format=yymmdd10.', 'FORMAT = comma18.2',
                                      'format=$char20.', 'format=8.2', 'format=best.',
                                      'format=8.', 'format=my_custom.'])
def test_proc_sql_formats_preserve_dependencies_columns_and_original_evidence(attribute: str) -> None:
    """Verify that proc sql formats preserve dependencies columns and original evidence.

    Args:
        attribute: Attribute value used by the test case.
    """
    statement = f'create table mart.x as\nselect a.event_date {attribute}, a.amount as total\nfrom raw.orders a where a.format=1;'
    result = parse_sas('proc sql;\n' + statement + '\nquit;')
    assert not result.diagnostics
    assert pairs(result) == {('raw.orders', 'mart.x')}
    operation = result.operations[0]
    assert operation.code == statement and (operation.start, operation.end) == (2, 4)
    assert operation.method == 'sas-proc-sql'
    assert {u.column for u in operation.usages} == {'event_date', 'amount', 'format'}


def test_proc_sql_format_length_and_calculated_do_not_invent_source_columns() -> None:
    """Verify that proc sql format length and calculated do not invent source columns."""
    statement = '''create table mart.x as select sum(a.amount) as total format=comma18.2,
        calculated total * 2 as doubled length=8,
        'format=date9. from raw.fake' as text format=$char40.
        from raw.orders a having calculated total > 0;'''
    result = parse_sas('proc sql;\n' + statement + '\nquit;')
    assert not result.diagnostics
    assert pairs(result) == {('raw.orders', 'mart.x')}
    assert {u.column for u in result.operations[0].usages} == {'amount'}
    assert result.operations[0].code == statement


def test_proc_sql_format_on_zero_argument_sas_datetime_retains_table_lineage() -> None:
    """Verify that proc sql format on zero argument sas datetime retains table lineage."""
    result = parse_sas('proc sql; create table pub.x as select a.id, datetime() as published_at format=datetime19. from raw.a a; quit;')
    assert pairs(result) == {('raw.a', 'pub.x')}
    assert not result.diagnostics
    assert {u.column for u in result.operations[0].usages} == {'id'}


@pytest.mark.parametrize('attribute', ['format=', 'format=date9', 'format=date9.evil', 'format=8.2extra'])
def test_proc_sql_invalid_format_is_diagnosed_without_guessed_edges(attribute: str) -> None:
    """Verify that proc sql invalid format is diagnosed without guessed edges.

    Args:
        attribute: Attribute value used by the test case.
    """
    result = parse_sas(f'proc sql; create table mart.x as select a.id {attribute} from raw.a a; quit;')
    assert not pairs(result)
    assert any(d.severity == 'error' for d in result.diagnostics)


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


@pytest.mark.parametrize('projection', ['a.id as value', 'a.id as missing, a.id as missing'])
def test_proc_sql_unknown_or_ambiguous_calculated_alias_is_diagnosed(projection: str) -> None:
    """Verify that proc sql unknown or ambiguous calculated alias is diagnosed.

    Args:
        projection: Projection value used by the test case.
    """
    result = parse_sas(f'proc sql; create table mart.x as select {projection}, calculated missing as derived from raw.a a; quit;')
    assert pairs(result) == {('raw.a', 'mart.x')}
    assert any('CALCULATED alias' in d.message and d.symbol == 'missing' for d in result.diagnostics)
    assert {u.column for u in result.operations[0].usages} == {'id'}


def test_proc_sql_modifiers_preserve_configured_tsql_projection_alias_rules() -> None:
    """Verify that proc sql modifiers preserve configured tsql projection alias rules."""
    result = parse_sas('proc sql; create table mart.x as select total = a.amount format=comma18.2 from raw.orders a; quit;',
                       sql_dialect='tsql')
    assert not result.diagnostics
    assert pairs(result) == {('raw.orders', 'mart.x')}
    assert {u.column for u in result.operations[0].usages} == {'amount'}


@pytest.mark.parametrize('alias', ['date', 'format', 'time'])
def test_proc_sql_calculated_accepts_keyword_aliases(alias: str) -> None:
    """Verify that proc sql calculated accepts keyword aliases.

    Args:
        alias: Alias value used by the test case.
    """
    result = parse_sas(f'proc sql; create table mart.x as select a.id as {alias}, calculated {alias} as derived from raw.a a; quit;')
    assert not result.diagnostics
    assert pairs(result) == {('raw.a', 'mart.x')}
    assert {u.column for u in result.operations[0].usages} == {'id'}
