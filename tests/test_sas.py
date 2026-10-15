from dataforge.parsers.csv import parse_csv
from dataforge.parsers.sas import parse_sas


def pairs(result):
    return {(s.name.lower(), t.name.lower()) for o in result.operations for s in o.sources for t in o.targets}


def test_csv_work_staging_proc_sql_and_columns():
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


def test_static_macros_libraries_and_ambiguous_macro():
    r = parse_sas('''%let src=raw;
data mart.x; set &src..orders; run;
data mart.y; set &unknown..orders; run;
%macro risky(); data mart.fake; set raw.fake; run; %mend;
%risky();''', library_mappings={"raw": "catalog.raw"})
    assert pairs(r) == {("catalog.raw.orders", "mart.x")}
    assert any("unknown" in d.message.lower() for d in r.diagnostics)
    assert not any("fake" in s for p in pairs(r) for s in p)


def test_common_procedures_and_data_merge():
    r = parse_sas('''data mart.joined; merge raw.a raw.b; by id; run;
proc sort data=mart.joined out=work.sorted; by id; run;
proc means data=work.sorted; output out=mart.stats; run;
proc transpose data=mart.stats out=mart.wide; run;
proc export data=mart.wide outfile="output/wide.csv" dbms=csv; run;''')
    assert pairs(r) == {("raw.a", "mart.joined"), ("raw.b", "mart.joined"),
                        ("mart.joined", "work.sorted"), ("work.sorted", "mart.stats"),
                        ("mart.stats", "mart.wide"), ("mart.wide", "file:output/wide.csv")}
    assert not any(u.table in {"raw.a", "raw.b"} for u in r.operations[0].usages)


def test_comments_and_literals_do_not_generate_phantom_edges():
    r = parse_sas('''/* data fake; set phantom; run; */
data mart.x; set raw.real; value="set raw.fake;"; run;
* data fake2; set raw.other; run;''')
    assert ("raw.fake", "mart.x") not in pairs(r)
    assert ("raw.real", "mart.x") in pairs(r)


def test_csv_schema_never_executes_values():
    r = parse_csv('id,name\n1,"create table bad as select * from secret"\n2,Ada\n', "input/x.csv")
    assert r.operations == []
    assert [c["name"] for c in r.metadata["columns"]] == ["id", "name"]
    assert r.metadata["row_count"] == 2
    assert r.assets[0].name == "file:input/x.csv"
