import json
import zipfile
from io import BytesIO

import pytest

from dataforge.database_maintenance import backup, restore_backup
from dataforge.migration import engine, service
from dataforge.store import Store


@pytest.mark.parametrize(("path", "code", "outputs"), [
    ("legacy.sas", "proc sql; create table a as select id from lib.input; quit; data b c; set a; run;",
     {"a", "b", "c"}),
    ("legacy.sql", "CREATE TABLE a AS SELECT 1 AS id; DELETE FROM a; CREATE VIEW b AS SELECT id FROM a;",
     {"a", "b"}),
])
def test_regions_outputs_and_blocked_dependencies(path, code, outputs):
    snapshot = {"sources": [{"id": "legacy", "path": path, "hash": engine.digest(code),
                             "text": code, "kind": path.split(".")[-1], "dialect": ""}],
                "catalog": "main", "schema": "migration", "warehouse": "databricks"}
    plan, files = engine.convert(snapshot)
    report = engine.validate(snapshot, plan, files)
    assert {output["name"] for output in plan["outputs"].values()} == outputs
    assert sum(row["end"] - row["start"] for row in plan["regions"]) == len(code)
    assert report["findings"]
    if "DELETE" in code:
        assert not report["active"]


def test_atomic_revision_and_export(tmp_path):
    store = Store(tmp_path)
    workspace = store.create_workspace("Migration")
    code = "CREATE TABLE a AS SELECT 1 AS id; CREATE VIEW b AS SELECT id FROM a;"
    project = service.create_project(store, workspace, "Example", {
        "sources": [{"id": "legacy", "path": "legacy.sql", "hash": engine.digest(code),
                     "text": code, "kind": "sql", "dialect": ""}],
        "catalog": "main", "schema": "migration", "warehouse": "databricks"})
    base = service.convert(store, workspace, project["id"], project["revision"])
    changes = {key: file["sql"] + "\n-- reviewed\n" for key, file in base["files"].items()}
    proposal = service.propose(base, changes, "Add a review note")
    with pytest.raises(ValueError):
        service.apply(store, workspace, project["id"], {**proposal, "base": "stale"})
    broken = service.propose(base, {"a": "SELECT 1 AS id, -- trailing separator\n"}, "Malformed provider draft")
    with pytest.raises(ValueError, match="unresolved SQL"):
        service.apply(store, workspace, project["id"], broken)
    assert service.load(store, workspace, project["id"])[1]["id"] == base["id"]
    result = service.apply(store, workspace, project["id"], proposal)
    assert all(file["sql"].endswith("-- reviewed\n") for file in result["files"].values())
    with pytest.raises(ValueError):
        service.apply(store, workspace, project["id"], proposal)
    with zipfile.ZipFile(BytesIO(service.bundle(store, workspace, project["id"], result["id"]))) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("migration/manifest.json"))
        assert manifest["revision"] == result["id"]
        assert manifest["runtime_equivalence"] == "not_evaluated"
        assert all(engine.digest(archive.read(path)) == item["sha256"] for path, item in manifest["files"].items())
        assert len([name for name in archive.namelist() if name.count("/") == 1 and name.endswith(".sql.txt")]) == 2
    restored_home = tmp_path.parent / (tmp_path.name + "_restored")
    restore_backup(backup(store), restored_home)
    store.close()
    restored = Store(restored_home)
    restored_project, restored_revision = service.load(restored, workspace, project["id"])
    assert restored_revision["id"] == result["id"]
    assert service.evidence(restored, workspace, restored_project["id"], restored_revision["plan"]["regions"][0]) in code
    for model in ("a", "b"):
        details = service.report(restored_project, restored_revision)
        obligations = [row["id"] for row in details["findings"] if row["model"] == model and not row["inherited_from"]]
        restored_revision = service.record_review(restored, workspace, project["id"], restored_revision["id"], model,
                                                  "Engineer", "Checked the original projection and dependency.", obligations)
    final = service.report(restored_project, restored_revision)
    assert final["eligible"] and set(final["active"].values()) == {"engineer_accepted"}
    assert set(final["tiers"].values()) == {"needs_investigation"}
    reviewed = service.bundle(restored, workspace, project["id"], restored_revision["id"], reviewed=True)
    with zipfile.ZipFile(BytesIO(reviewed)) as archive:
        row = next(item for item in json.loads(archive.read("migration/source-map.json")) if item["model"] == "a")
        assert archive.read(row["artifact"]).decode() == restored_revision["files"]["a"]["sql"]
        assert "engineer_review" in archive.read(row["annotation_artifact"]).decode()
    restored.close()

def test_dbt_preserves_model_bytes_and_quarantines_templates(tmp_path, monkeypatch):
    import subprocess

    from jinja2 import Template

    def unexpected_execution(*_args, **_kwargs):
        pytest.fail("Static migration attempted to run code")

    monkeypatch.setattr(subprocess, "Popen", unexpected_execution)
    monkeypatch.setattr(Template, "render", unexpected_execution)
    store = Store(tmp_path)
    workspace = store.create_workspace("dbt migration")
    contents = {
        "dbt_project.yml": "name: legacy\nversion: '1.0'\nconfig-version: 2\nmodels:\n  legacy:\n    +materialized: table\n",
        "models/a.sql": "{{ config(alias='input_rows') }}\nselect 1 as id\n",
        "models/b.sql": "select id from {{ ref('legacy', 'a') }}\n",
        "models/unsafe.sql": "select {{ run_query('drop table xyz') }} as id\n",
    }
    snapshot = {"sources": [
        {"id": path, "path": path, "hash": engine.digest(sql), "text": sql, "kind": "dbt",
         "role": "project" if path == "dbt_project.yml" else "model", "dialect": "databricks"}
        for path, sql in contents.items()
    ], "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    project = service.create_project(store, workspace, "dbt", snapshot)
    result = service.convert(store, workspace, project["id"], project["revision"])
    with zipfile.ZipFile(BytesIO(service.bundle(store, workspace, project["id"], result["id"]))) as archive:
        assert archive.read("models/b.sql").decode() == contents["models/b.sql"]
        assert "models/unsafe.sql" not in archive.namelist()
        assert b"materialized: table" in archive.read("models/schema.yml")
    with pytest.raises(ValueError, match="required outputs"):
        service.bundle(store, workspace, project["id"], result["id"], reviewed=True)
    store.close()


def test_schema_unknown_and_broken_downstream_column(tmp_path):
    store = Store(tmp_path)
    workspace = store.create_workspace("Schemas")
    code = ("CREATE TABLE a AS SELECT id FROM main.raw.accounts; "
            "CREATE VIEW b AS SELECT id FROM a WHERE id > 10;")
    project = service.create_project(store, workspace, "Schemas", {
        "sources": [{"id": "legacy", "path": "legacy.sql", "hash": engine.digest(code),
                     "text": code, "kind": "sql", "dialect": ""}],
        "catalog": "main", "schema": "migration", "warehouse": "databricks"})
    base = service.convert(store, workspace, project["id"], project["revision"])
    loaded, _ = service.load(store, workspace, project["id"])
    report = service.report(loaded, base)
    assert report["schemas"]["a"]["id"]["target_type"] == "STRING"
    assert report["schemas"]["a"]["id"]["provenance"] == "assumed_string"
    assert "CAST" not in base["files"]["a"]["sql"]
    assert report["tiers"]["b"] == "needs_investigation"
    updated = service.revise_schemas(store, workspace, project["id"], base["id"],
                                     {"input_types": {next(iter(base["plan"]["physical"])): {"id": "INT"}}})
    assert service.report(loaded, updated)["eligible"]
    old_sql = updated["files"]["a"]["sql"]
    proposal = service.propose(updated, {"a": old_sql.replace("id", "other", 1)}, "Change the projected column")
    with pytest.raises(ValueError, match="dependency"):
        service.apply(store, workspace, project["id"], proposal)
    assert service.load(store, workspace, project["id"])[1]["id"] == updated["id"]
    store.close()


def test_provider_preview_and_unknown_outcome_recovery(tmp_path, monkeypatch):
    import httpx

    from dataforge.llm import Profile
    from dataforge.migration import assistance
    from dataforge.model_capabilities import ModelCapabilities, bind_capabilities

    store = Store(tmp_path)
    workspace = store.create_workspace("Assistance")
    other = store.create_workspace("Other")
    profile = Profile(provider="LM Studio", base_url="http://localhost:1234/v1", model="migration",
                      source_limit_policy="token_capacity")
    profile = profile.model_copy(update={"model_capabilities": bind_capabilities(
        ModelCapabilities(context_tokens=32_000, output_tokens=2048, source="manual"), profile)})
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["profile", workspace, "Test", profile.model_dump_json()])
    secret = "migration_canary_secret_x9"
    monkeypatch.setenv("MIGRATION_TEST_SECRET", secret)
    code = f"CREATE VIEW a AS SELECT 1 AS id; CREATE VIEW b AS SELECT id FROM a; -- {secret}"
    project = service.create_project(store, workspace, "Assistant", {
        "sources": [{"id": "legacy", "path": "legacy.sql", "hash": engine.digest(code),
                     "text": code, "kind": "sql", "dialect": ""}],
        "catalog": "main", "schema": "migration", "warehouse": "databricks"})
    base = service.convert(store, workspace, project["id"], project["revision"])
    args = (store, workspace, project["id"], base["id"], "profile", ["a", "b"], "convert", secret)
    prepared = assistance.prepare(*args)
    assert secret not in json.dumps(prepared["request"])
    wire_format = prepared["request"][1]["response_format"]
    assert wire_format["type"] == "json_schema"
    edits_schema = wire_format["json_schema"]["schema"]["properties"]["edits"]
    assert edits_schema["required"] == ["a", "b"]
    assert edits_schema["properties"]["b"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    with pytest.raises(ValueError, match="workspace"):
        service.load(store, other, project["id"])
    assert not assistance.attempts(store, workspace, project["id"])

    def timeout(request):
        assert secret not in request.content.decode()
        raise httpx.ReadTimeout("simulated", request=request)

    with pytest.raises(ValueError, match="reservation"):
        assistance.dispatch(*args, prepared["pin"], transport=httpx.MockTransport(timeout))
    journal = assistance.attempts(store, workspace, project["id"])
    assert len(journal) == 1 and journal[0]["status"] == "unknown"
    assert journal[0]["reserved"] == prepared["tokens"]
    store.close()
    store = Store(tmp_path)
    assert assistance.attempts(store, workspace, project["id"])[0]["status"] == "unknown"

    def complete(_request):
        # An unchanged candidate with different surrounding whitespace should keep its prior revision.
        b = base["files"]["b"]["sql"].rstrip() if store.setting(workspace, "llm_history", False) else " \n"
        payload = {"answer": "Draft a; account for b separately.", "citations": ["r1", "r2"],
                   "edits": {"a": "SELECT 2 AS id", "b": b}}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)},
                                                     "finish_reason": "stop"}]})

    response = assistance.dispatch(store, *args[1:], prepared["pin"], transport=httpx.MockTransport(complete))
    assert response["missing_outputs"] == ["b"]
    assert service.load(store, workspace, project["id"])[1]["files"] == base["files"]
    assert response["proposal"]["base"] == base["id"]
    assert not assistance.responses(store, workspace, project["id"])
    store.set_setting(workspace, "llm_history", True)
    accounted = assistance.dispatch(store, *args[1:], prepared["pin"], transport=httpx.MockTransport(complete))
    assert not accounted["missing_outputs"]
    saved = assistance.responses(store, workspace, project["id"])[0]["proposal"]
    assert saved["base"] == base["id"]
    assert set(saved["edits"]) == {"a"}
    store.set_setting(workspace, "llm_history", False)
    assert not assistance.responses(store, workspace, project["id"])
    assert len(assistance.attempts(store, workspace, project["id"])) == 3
    store.close()

@pytest.mark.parametrize(("query", "expected"), [
    ("SELECT bad.id FROM a", "missing_column"),
    ("SELECT id FROM a JOIN b ON a.id = b.id", "missing_column"),
    ("WITH p AS (SELECT absent FROM a) SELECT absent FROM p", "missing_column"),
    ("SELECT code + 1 AS adjusted FROM a", "unknown_sensitive_type"),
    ("SELECT id FROM a WHERE code > 10", "unknown_sensitive_type"),
])
def test_invalid_or_unproven_column_bindings_block_reviewed_export(query, expected):
    code = f"CREATE VIEW a AS SELECT 1 AS id, 'ABC' AS code; CREATE VIEW b AS SELECT 2 AS id; CREATE VIEW c AS {query};"
    snapshot = {"sources": [{"id": "s", "path": "example.sql", "kind": "sql", "hash": engine.digest(code),
                             "text": code}], "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    plan, files = engine.convert(snapshot)
    report = engine.validate(snapshot, plan, files)
    assert expected in {item["code"] for item in report["findings"]}
    assert "c" not in report["active"] and not report["eligible"]


@pytest.mark.parametrize("statement", [
    "CREATE PROCEDURE compile_stage() BEGIN CREATE TABLE main.raw.stage AS SELECT 1 AS id; END;",
    "EXECUTE IMMEDIATE 'CREATE TABLE main.raw.stage AS SELECT 1 AS id';",
])
def test_excluding_opaque_known_producer_keeps_consumer_blocked(tmp_path, statement):
    programs = {
        "stage.sql": statement,
        "child.sql": "CREATE VIEW child AS SELECT id FROM main.raw.stage;",
    }
    snapshot = {"sources": [{"id": path, "path": path, "kind": "sql", "hash": engine.digest(code), "text": code}
                             for path, code in programs.items()],
                "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    store = Store(tmp_path)
    workspace = store.create_workspace("Producer")
    project = service.create_project(store, workspace, "Producer", snapshot)
    base = service.convert(store, workspace, project["id"], project["revision"])
    updated = service.resolve_scope(store, workspace, project["id"], base["id"], "r1", "Keep the legacy procedure.")
    loaded, _ = service.load(store, workspace, project["id"])
    assert "child" not in service.report(loaded, updated)["active"]
    store.close()


def test_generated_target_cannot_match_physical_source():
    docs = {
        "dbt_project.yml": ("project", "name: legacy\nversion: '1.0'\nconfig-version: 2\n"),
        "models/sources.yml": ("model", "version: 2\nsources:\n- name: legacy\n  database: main\n"
                                        "  schema: migration\n  tables:\n  - name: accounts\n"),
        "models/accounts.sql": ("model", "select id from {{ source('legacy', 'accounts') }}"),
    }
    snapshot = {"sources": [{"id": path, "path": path, "kind": "dbt", "role": role, "dialect": "databricks",
                             "hash": engine.digest(text), "text": text} for path, (role, text) in docs.items()],
                "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    plan, files = engine.convert(snapshot)
    report = engine.validate(snapshot, plan, files)
    assert "target_collision" in {item["code"] for item in report["findings"]}
    assert not report["eligible"]


def test_cancelled_conversion_reuses_saved_lowering_after_restart(tmp_path, monkeypatch):
    code = "CREATE VIEW a AS SELECT 1 AS id; CREATE VIEW b AS SELECT id FROM a;"
    snapshot = {"sources": [{"id": "s", "path": "input.sql", "kind": "sql", "hash": engine.digest(code),
                             "text": code}], "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    store = Store(tmp_path)
    workspace = store.create_workspace("Resume")
    project = service.create_project(store, workspace, "Resume", snapshot)
    lowered = []
    original = engine._inputs

    def count(query, *args):
        lowered.append(query.selects[0].sql())
        return original(query, *args)

    monkeypatch.setattr(engine, "_inputs", count)
    with pytest.raises(InterruptedError):
        service.convert(store, workspace, project["id"], project["revision"], cancelled=lambda: bool(lowered))
    assert lowered == ["1 AS id"]
    assert service.load(store, workspace, project["id"])[1]["plan"] is None
    store.close()
    store = Store(tmp_path)
    resumed = service.convert(store, workspace, project["id"], project["revision"])
    assert lowered == ["1 AS id", "id"]
    assert set(resumed["files"]) == {"a", "b"}
    assert not store.rows("SELECT 1 FROM migration_activity WHERE kind='checkpoint'")
    store.close()

def test_draft_bundle_keeps_untranslated_outputs_and_opaque_source_lines(tmp_path):
    programs = {
        "normal.sql": "CREATE VIEW good AS SELECT 1 AS id;",
        "procedure.sql": "CREATE PROCEDURE make_legacy() BEGIN\nCREATE TABLE main.raw.legacy AS SELECT 1 AS id;\nEND;",
        "dynamic.sql": "EXECUTE IMMEDIATE 'select {{ run_query(1) }}';",
    }
    store = Store(tmp_path)
    workspace = store.create_workspace("Annotated drafts")
    project = service.create_project(store, workspace, "Annotated", {
        "sources": [{"id": path, "path": path, "kind": "sql", "hash": engine.digest(code), "text": code}
                    for path, code in programs.items()],
        "warehouse": "databricks", "catalog": "main", "schema": "migration"})
    revision = service.convert(store, workspace, project["id"], project["revision"])
    service.add_review_comment(store, workspace, project["id"], revision["id"], "legacy", "source", 2,
                               "Engineer", "Confirm who owns this relation.")
    with pytest.raises(ValueError, match="outside"):
        service.add_review_comment(store, workspace, project["id"], revision["id"], "legacy", "source", 9,
                                   "Engineer", "Unexpected line")
    note, = service.review_comments(store, workspace, project["id"])
    assert note["revision"] == revision["id"] and note["line"] == 2
    service.resolve_review_comment(store, workspace, project["id"], note["id"])
    assert service.review_comments(store, workspace, project["id"])[0]["status"] == "resolved"

    with zipfile.ZipFile(BytesIO(service.bundle(store, workspace, project["id"], revision["id"]))) as bundle:
        assert "models/good.sql" in bundle.namelist()
        missing = bundle.read("review/legacy.sql.txt").decode()
        assert "REVIEW REQUIRED" in missing and all(line.startswith("--") for line in missing.splitlines())
        source_map = json.loads(bundle.read("migration/source-map.json"))
        assert {row["source"] for row in source_map} == set(programs)
        opaque = next(row for row in source_map if row["source"] == "dynamic.sql")
        evidence = bundle.read(opaque["artifact"]).decode()
        assert "EXECUTE IMMEDIATE" in evidence and "{{" not in evidence
        assert all(line.startswith("--") for line in evidence.splitlines())
    with pytest.raises(ValueError, match="required outputs"):
        service.bundle(store, workspace, project["id"], revision["id"], reviewed=True)
    store.close()


def test_sas_two_branch_draft_retains_both_dependencies_and_null_review():
    code = ("proc sql; create table stage as select id from raw.accounts; quit;\n"
            "data low high; set stage; if id < 10 then output low; else output high; run;")
    snapshot = {"sources": [{"id": "root", "path": "input.sas", "kind": "sas", "text": code,
                             "hash": engine.digest(code)}],
                "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    plan, files = engine.convert(snapshot)
    assert set(files) == {"stage", "low", "high"}
    assert all("{{ ref('stage') }}" in files[model]["sql"] for model in ("low", "high"))
    assert "NOT" in files["high"]["sql"] and "NOT" not in files["low"]["sql"]
    report = engine.validate(snapshot, plan, files)
    critical = {finding["model"]: finding["message"] for finding in report["findings"]
                if finding["code"] == "critical_source"}
    assert set(critical) == {"low", "high"} and all("both exclude NULL" in reason for reason in critical.values())
    assert not report["eligible"]


def test_select_into_draft_keeps_named_output_and_removes_write_syntax():
    code = "SELECT 1 AS id INTO stage; CREATE VIEW consumer AS SELECT id FROM stage;"
    snapshot = {"sources": [{"id": "root", "path": "input.sql", "kind": "sql", "text": code,
                             "hash": engine.digest(code), "dialect": "tsql"}],
                "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    plan, files = engine.convert(snapshot)
    assert set(files) == {"stage", "consumer"}
    assert "INTO" not in files["stage"]["sql"]
    assert "{{ ref('stage') }}" in files["consumer"]["sql"]
    with pytest.raises(ValueError):
        engine.inspect_sql("SELECT 1 AS id INTO stage", "databricks")

def test_sql_comment_keywords_do_not_hide_convertible_models():
    code = ("-- create procedure in the future\nCREATE VIEW a AS SELECT 'create function' AS message;\n"
            "/* begin transaction */ CREATE VIEW b AS SELECT message FROM a;")
    snapshot = {"sources": [{"id": "s", "path": "input.sql", "kind": "sql", "text": code,
                             "hash": engine.digest(code)}],
                "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    plan, files = engine.convert(snapshot)
    assert set(files) == {"a", "b"} and engine.validate(snapshot, plan, files)["eligible"]


@pytest.mark.parametrize(("middle", "expected"), [
    ("EXECUTE IMMEDIATE 'select 2; select 3';", {"a", "b"}),
    ("CREATE PROCEDURE p() BEGIN CREATE VIEW inner_view AS SELECT 2 AS id; END;", {"a"}),
])
def test_opaque_sql_preserves_independent_conversion_without_lowering_procedure_body(middle, expected):
    code = "CREATE VIEW a AS SELECT 1 AS id; " + middle + " CREATE VIEW b AS SELECT id FROM a;"
    snapshot = {"sources": [{"id": "s", "path": "input.sql", "kind": "sql", "text": code,
                             "hash": engine.digest(code)}],
                "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    plan, files = engine.convert(snapshot)
    assert set(files) == expected
    assert not engine.validate(snapshot, plan, files)["eligible"]
    assert sum(row["end"] - row["start"] for row in plan["regions"]) == len(code)


@pytest.mark.parametrize("sql", ["SELECT FROM {{ ref('upstream') }}", "WITH p AS (SELECT) SELECT 1 AS id"])
def test_target_sql_rejects_empty_select_projections(sql):
    with pytest.raises(ValueError, match="projection"):
        engine.inspect_sql(sql, "databricks")


@pytest.mark.parametrize("query", [
    "SELECT 1 AS id UNION ALL (SELECT 2 AS id, 3 AS extra)",
    "WITH p AS (SELECT 1 AS id UNION ALL SELECT 2 AS id, 3 AS extra) SELECT id FROM p",
])
def test_set_operation_layout_check_covers_nested_and_parenthesized_branches(query):
    code = f"CREATE VIEW a AS {query};"
    snapshot = {"sources": [{"id": "s", "path": "input.sql", "kind": "sql", "text": code, "hash": engine.digest(code)}],
                "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    plan, files = engine.convert(snapshot)
    report = engine.validate(snapshot, plan, files)
    assert report["tiers"]["a"] == "blocked"
    assert any(item["code"] == "set_layout" for item in report["findings"])


def test_cycle_does_not_hide_qualified_unrelated_dependency_chain():
    code = ("CREATE VIEW z AS SELECT 1 AS id; CREATE VIEW a AS SELECT id FROM z; "
            "CREATE VIEW x AS SELECT id FROM y; CREATE VIEW y AS SELECT id FROM x;")
    snapshot = {"sources": [{"id": "s", "path": "input.sql", "kind": "sql", "text": code, "hash": engine.digest(code)}],
                "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    plan, files = engine.convert(snapshot)
    report = engine.validate(snapshot, plan, files)
    assert set(report["active"]) == {"z", "a"} and not report["eligible"]


def test_sas_block_comments_do_not_hide_static_drafts():
    code = "data first; set raw.accounts; /* %include was removed */ keep id; run;"
    snapshot = {"sources": [{"id": "s", "path": "input.sas", "kind": "sas", "text": code, "hash": engine.digest(code)}],
                "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    plan, files = engine.convert(snapshot)
    assert set(files) == {"first"}
    assert "include" not in files["first"]["sql"].lower()
    assert not engine.validate(snapshot, plan, files)["eligible"]
