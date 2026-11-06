import pytest

from dataforge.parsers.sas_sql import parse_proc_sql
from dataforge.parsers.sql import parse_sql


def names(refs):
    return [ref.name for ref in refs]


def test_sas_proc_sql_with_databricks_dialect_retains_its_parser():
    parsed = parse_proc_sql(
        "CREATE TABLE sink AS SELECT raw.id FORMAT=BEST12. FROM raw",
        "databricks",
    )
    (op,) = parsed.operations
    assert names(op.sources) == ["raw"]
    assert names(op.targets) == ["sink"]


def test_use_applies_in_order_to_physical_tables_and_resets_schema():
    parsed = parse_sql(
        "USE CATALOG `raw.zone`; USE SCHEMA staging;\n"
        "CREATE TABLE typed USING DELTA AS "
        "WITH source AS (SELECT id FROM raw_feed), unused AS (SELECT id FROM ignored) "
        "SELECT source.id FROM source;\n"
        "USE CATALOG curated; CREATE TABLE sink AS SELECT a.id FROM staging.typed AS a;\n"
        "USE SCHEMA shared.reporting; INSERT INTO totals (id) SELECT id FROM external.full.table;",
        "databricks",
    )
    first, second, third = parsed.operations
    assert names(first.sources) == ['"raw.zone".staging.raw_feed']
    assert names(first.targets) == ['"raw.zone".staging.typed']
    assert any(item["table"] == '"raw.zone".staging.raw_feed'
               for item in first.derivations[0]["inputs"])
    assert names(second.sources) == ["curated.staging.typed"]
    assert names(second.targets) == ["curated.default.sink"]
    assert names(third.sources) == ["external.full.table"]
    assert names(third.targets) == ["shared.reporting.totals"]
    isolated = parse_sql("SELECT id FROM raw_feed;", "databricks")
    assert names(isolated.operations[0].sources) == ["raw_feed"]


def test_use_applies_to_outer_dml_and_typed_delta_ddl():
    parsed = parse_sql(
        "USE CATALOG main; USE SCHEMA work; "
        "CREATE TABLE sink (id INT, payload STRING) USING DELTA; "
        "UPDATE sink AS t SET payload = src.payload FROM shared.events AS src WHERE t.id = src.id;",
        "databricks",
    )
    assert names(parsed.operations[-1].targets) == ["main.work.sink"]
    assert names(parsed.operations[-1].sources) == ["main.shared.events"]
    schema = parsed.metadata["declared_schemas"][0]
    assert schema["table"] == "main.work.sink"
    assert schema["column_identifiers"] == ["id", "payload"]


def test_set_query_namespaces_only_reachable_physical_relations():
    parsed = parse_sql(
        "USE CATALOG main; USE SCHEMA work; "
        "WITH chosen AS (SELECT id FROM raw), unused AS (SELECT id FROM ignored) "
        "SELECT id FROM chosen EXCEPT SELECT id FROM deny;",
        "databricks",
    )
    assert set(names(parsed.operations[0].sources)) == {"main.work.raw", "main.work.deny"}


def test_stream_preserves_literal_source_alias_and_statement_evidence():
    code = "CREATE STREAMING TABLE output AS SELECT f.id FROM STREAM(raw_feed) AS f;"
    parsed = parse_sql("USE CATALOG main; USE SCHEMA work;\n" + code, "databricks")
    (op,) = parsed.operations
    assert names(op.sources) == ["main.work.raw_feed"]
    assert names(op.targets) == ["main.work.output"]
    assert op.code.rstrip(";") == code.rstrip(";")
    assert op.start == op.end == 2
    assert op.derivations[0]["expression"] == "f.id"
    assert [(i["table"], i["column"]) for i in op.derivations[0]["inputs"]] == [("main.work.raw_feed", "id")]
    generic = parse_sql(code, "")
    assert all("raw_feed" not in names(op.sources) for op in generic.operations)


def test_stream_keyword_with_options_binds_quoted_struct_path():
    parsed = parse_sql(
        "USE CATALOG main; USE SCHEMA work; "
        "CREATE TABLE sink AS SELECT f.soil.`ph.level` AS level "
        "FROM STREAM shared.feed WITH (readChangeFeed = true) AS f;",
        "databricks",
    )
    (op,) = parsed.operations
    assert names(op.sources) == ["main.shared.feed"]
    assert [(u.table, u.column) for u in op.usages] == [("main.shared.feed", 'soil."ph.level"')]
    assert not parsed.diagnostics


def test_direct_usage_keeps_deep_struct_fields_and_stars():
    parsed = parse_sql(
        "SELECT f.soil.depth.reading.`ph.level` AS ph, f.soil.depth.reading.* FROM main.work.feed AS f;",
        "databricks",
    )
    (op,) = parsed.operations
    assert {(u.table, u.column) for u in op.usages} == {
        ("main.work.feed", 'soil.depth.reading."ph.level"'), ("main.work.feed", "soil.depth.reading.*"),
    }
    assert all(not u.wildcard_safe for u in op.usages)


@pytest.mark.parametrize("source", ["STREAM(feed)", "STREAM feed"])
def test_stream_binding_retains_pivot_value_and_key(source):
    parsed = parse_sql(
        f"CREATE TABLE sink AS SELECT east FROM {source} "
        "PIVOT (SUM(amount) FOR region IN ('east'));",
        "databricks",
    )
    (op,) = parsed.operations
    assert names(op.sources) == ["feed"]
    east = next(d for d in op.derivations if d["target_column"] == "east")
    assert {(i["column"], i["role"]) for i in east["inputs"]} >= {
        ("amount", "value"), ("region", "value_selection"),
    }


def test_dynamic_stream_retains_diagnostic_without_inventing_source():
    parsed = parse_sql(
        "CREATE STREAMING TABLE sink AS SELECT f.id FROM STREAM(IDENTIFIER(:input)) AS f;",
        "databricks",
    )
    (op,) = parsed.operations
    assert names(op.sources) == []
    assert names(op.targets) == ["sink"]
    assert op.usages == []
    assert op.derivations[0]["status"] == "unresolved"
    assert any("STREAM" in diagnostic.message for diagnostic in parsed.diagnostics)


@pytest.mark.parametrize("kind", ["LIVE TABLE", "STREAMING LIVE TABLE"])
def test_legacy_dlt_live_table_expectation(kind):
    code = (f"CREATE OR REFRESH {kind} sink (CONSTRAINT valid EXPECT (id > 0)) "
            "AS SELECT id FROM STREAM(raw);")
    parsed = parse_sql(code, "databricks")
    (op,) = parsed.operations
    assert names(op.sources) == ["raw"]
    assert names(op.targets) == ["sink"]
    assert op.code.rstrip(";") == code.rstrip(";")
    (record,) = op.derivations
    assert record["target_column"] == "id"
    assert {(item["column"], item["role"]) for item in record["inputs"]} == {
        ("id", "value"), ("id", "quality_warn"),
    }


@pytest.mark.parametrize("suffix, policy", [
    ("", "warn"), (" ON VIOLATION DROP ROW", "drop"), (" ON VIOLATION FAIL UPDATE", "fail"),
])
def test_expect_is_quality_evidence_over_projected_columns(suffix, policy):
    rule = "CONSTRAINT positive_amount EXPECT (amount > 0)" + suffix
    code = f"CREATE STREAMING TABLE sink ({rule}) AS SELECT raw_amount AS amount FROM raw;"
    parsed = parse_sql(code, "databricks")
    (op,) = parsed.operations
    assert names(op.sources) == ["raw"]
    assert names(op.targets) == ["sink"]
    assert all(d["target_column"] != "positive_amount" for d in op.derivations)
    assert parsed.metadata["declared_schemas"][0]["columns"] is None
    amount = next(d for d in op.derivations if d["target_column"] == "amount")
    assert amount["status"] == "verified"
    assert (("raw", "raw_amount", f"quality_{policy}") in
            {(i["table"], i["column"], i["role"]) for i in amount["inputs"]})
    assert rule in op.code


def test_cdc_pipeline_binds_declared_target_and_separates_payload_and_controls():
    flow = (
        "CREATE FLOW apply_feed AS AUTO CDC INTO history\n"
        "FROM STREAM(cleaned) KEYS (id) APPLY AS DELETE WHEN event = 'delete'\n"
        "SEQUENCE BY STRUCT(seq, tie_breaker) COLUMNS (id, payload)\n"
        "STORED AS SCD TYPE 2 TRACK HISTORY ON (payload);"
    )
    parsed = parse_sql(
        "USE CATALOG main; USE SCHEMA pipeline;\n"
        "CREATE STREAMING TABLE cleaned (CONSTRAINT valid EXPECT (id > 0) ON VIOLATION DROP ROW) "
        "AS SELECT id, payload, event, seq, tie_breaker FROM STREAM(raw);\n"
        "CREATE STREAMING TABLE history;\n" + flow,
        "databricks",
    )
    cleaned, declared, applied = parsed.operations
    assert names(cleaned.sources) == ["main.pipeline.raw"]
    assert names(declared.targets) == names(applied.targets) == ["main.pipeline.history"]
    assert names(applied.sources) == ["main.pipeline.cleaned"]
    assert applied.code.rstrip(";") == flow.rstrip(";")
    assert all(d["target_column"] != "valid" for d in cleaned.derivations)
    payload = next(d for d in applied.derivations if d["target_column"] == "payload")
    assert payload["expression"] == "payload"
    assert {(i["column"], i["role"]) for i in payload["inputs"]} == {
        ("payload", "value"), ("id", "match_key"), ("event", "delete_condition"),
        ("seq", "sequence"), ("tie_breaker", "sequence"), ("payload", "history"),
    }
    assert {d["target_column"] for d in applied.derivations if not d["scope"]} == {"id", "payload"}


def test_inline_cdc_wildcard_keeps_coverage_for_incomplete_schemas():
    parsed = parse_sql(
        "CREATE OR REFRESH STREAMING TABLE history FLOW AUTO CDC "
        "FROM STREAM raw WITH (readChangeFeed = true) KEYS (id) "
        "SEQUENCE BY seq COLUMNS * EXCEPT (seq) STORED AS SCD TYPE 2 "
        "TRACK HISTORY ON * EXCEPT (id);",
        "databricks",
    )
    (op,) = parsed.operations
    assert names(op.sources) == ["raw"]
    assert names(op.targets) == ["history"]
    (wildcard,) = op.derivations
    assert wildcard["target_column"] == "*"
    assert wildcard["status"] == "unresolved"
    assert {(i["column"], i["role"]) for i in wildcard["inputs"]} >= {
        ("*", "value"), ("id", "match_key"), ("seq", "sequence"),
    }


def test_scd2_tracks_explicit_payload_by_default():
    parsed = parse_sql(
        "CREATE FLOW f AS AUTO CDC INTO history FROM STREAM(feed) "
        "KEYS (id) SEQUENCE BY seq COLUMNS (id, payload) STORED AS SCD TYPE 2;",
        "databricks",
    )
    (op,) = parsed.operations
    payload = next(d for d in op.derivations if d["target_column"] == "payload")
    assert {i["column"] for i in payload["inputs"] if i["role"] == "history"} == {"id", "payload"}


def test_malformed_cdc_does_not_interrupt_later_statements():
    parsed = parse_sql(
        "CREATE FLOW f AS AUTO CDC INTO history FROM STREAM(feed) "
        "KEYS (id) SEQUENCE BY seq COLUMNS ();\n"
        "CREATE TABLE sink AS SELECT id FROM valid;",
        "databricks",
    )
    assert any(d.line == 1 and d.severity == "error" for d in parsed.diagnostics)
    (op,) = parsed.operations
    assert names(op.sources) == ["valid"]
    assert names(op.targets) == ["sink"]
