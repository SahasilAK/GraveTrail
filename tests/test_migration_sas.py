from dataforge.migration.sources import sas_units


def test_sas_step_boundaries_and_dynamic_regions_preserve_literal_outputs():
    source = """%let lib=raw;
%let input=&lib..orders;
proc sql;
  create table stage as select id from &input.;
  run;
  create table next_stage as select id from stage;
data filtered;
  set next_stage;
  keep id;
data copied;
  set filtered;
  keep id;
run;
%macro optional;
  data conditional; set raw.orders; keep id; run;
%mend;
data inline;
  input id;
  /* Retain the complete input body */ datalines4;
  proc sql; create table apparent as select 1;
;;;;
run;
data final;
  set filtered;
  keep id;
run;"""
    regions = list(sas_units(source))
    assert "".join(source[start:end] for start, end, *_ in regions) == source
    by_output = {name: (source[start:end], query, gap)
                 for start, end, query, names, gap, _ in regions for name in names}
    assert set(by_output) == {"stage", "next_stage", "filtered", "copied", "conditional", "inline", "final"}
    assert by_output["stage"][1].sql() == "SELECT id FROM raw.orders"
    assert by_output["next_stage"][0] == "create table next_stage as select id from stage;"
    assert by_output["filtered"][0] == "data filtered;\n  set next_stage;\n  keep id;"
    assert by_output["filtered"][1].sql() == "SELECT id FROM next_stage"
    assert by_output["conditional"][1] is None and "macros" in by_output["conditional"][2]
    assert by_output["inline"][1] is None and "inline SAS data" in by_output["inline"][2]
    assert by_output["final"][1].sql() == "SELECT id FROM filtered"


def test_sas_projection_order_and_remerge_preserve_detail_grain():
    source = """data projected(rename=(mid=final) keep=id mid);
  set raw.orders(rename=(amount=net) keep=id amount scratch);
  total = net + 1;
  if net > 0;
  rename total=mid;
  drop scratch;
  keep id total;
run;
data dropped(drop=extra);
  set raw.orders(drop=scratch);
  drop internal;
run;
data limited;
  set raw.orders(obs=10);
  keep id;
run;
data stale;
  set raw.orders(keep=id amount rename=(amount=net));
  keep id amount;
run;
proc sql;
  create table detail as select account, id, sum(amount) as total
    from raw.orders group by account;
  create table summary as select account, sum(amount) as total
    from raw.orders group by account;
  create table ambiguous as select account, max(amount) as max_amount
    from raw.orders group by account having amount = max(amount);
quit;"""
    by_output = {name: (source[start:end], query, gap)
                 for start, end, query, names, gap, _ in sas_units(source) for name in names}
    assert by_output["projected"][1].sql() == "SELECT id, amount + 1 AS final FROM raw.orders WHERE amount > 0"
    assert by_output["dropped"][1].sql(dialect="databricks") == "SELECT * EXCEPT (extra, internal, scratch) FROM raw.orders"
    assert by_output["limited"][1] is None and "SET dataset options" in by_output["limited"][2]
    assert by_output["stale"][1] is None and "amount" in by_output["stale"][2]

    retained, detail, gap = by_output["detail"]
    assert "group by account" in retained
    assert detail.sql(dialect="databricks") == (
        "SELECT account, id, SUM(amount) OVER (PARTITION BY account) AS total FROM raw.orders"
    )
    assert "remerge" in gap and "detail" in gap
    assert detail.meta["migration_sas_remerge"]["detail_columns"] == ["id"]
    assert by_output["summary"][1].args.get("group") and not by_output["summary"][2]
    assert by_output["ambiguous"][1].args.get("having")
    assert "remerge" in by_output["ambiguous"][2]


def test_sas_set_stack_projects_the_same_columns_and_retains_all_rows():
    source = """data stacked(keep=second first);
  set raw.jan raw.feb raw.jan;
run;
data statement_keep;
  keep first;
  set raw.jan raw.feb;
run;
data open_layout;
  set raw.jan raw.feb;
run;
data input_options;
  set raw.jan(keep=first) raw.feb;
  keep first;
run;"""
    by_output = {name: (query, gap)
                 for _, _, query, names, gap, _ in sas_units(source) for name in names}
    stack, gap = by_output["stacked"]
    projection = "SELECT second, first FROM "
    assert stack.sql() == " UNION ALL ".join(projection + table for table in ("raw.jan", "raw.feb", "raw.jan"))
    assert stack.meta["migration_sas_stack"]["columns"] == ["second", "first"]
    assert "ordering" in gap and "missing" in gap
    assert by_output["statement_keep"][0].sql() == "SELECT first FROM raw.jan UNION ALL SELECT first FROM raw.feb"
    for name in ("open_layout", "input_options"):
        query, gap = by_output[name]
        assert query is None and "SET concatenation" in gap


def test_sas_two_branch_draft_applies_shared_and_per_output_projections():
    source = """data work.Low(keep=id amount) work.High(drop=amount);
  set raw.orders;
  if amount < 10 then output work.low;
  else output work.high;
  keep id amount;
run;"""
    _, _, queries, names, gap, _ = next(sas_units(source))
    assert names == ["work.Low", "work.High"]
    assert queries["work.Low"].sql() == "SELECT id, amount FROM raw.orders WHERE amount < 10"
    assert queries["work.High"].sql() == "SELECT id FROM raw.orders WHERE NOT (amount < 10)"
    assert "both exclude NULL" in gap

    _, _, dropped, _, _, _ = next(sas_units(source.replace("keep id amount;", "drop score;")))
    assert dropped["work.Low"].sql() == "SELECT id, amount FROM raw.orders WHERE amount < 10"
    assert dropped["work.High"].sql(dialect="databricks") == (
        "SELECT * EXCEPT (amount, score) FROM raw.orders WHERE NOT (amount < 10)"
    )
