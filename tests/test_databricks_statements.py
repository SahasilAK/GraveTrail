
from dataforge.parsers.sql import parse_sql


def names(refs):
    return [ref.name for ref in refs]


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
