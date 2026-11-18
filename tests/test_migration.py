import csv
import json
import zipfile
from contextlib import closing
from io import BytesIO, StringIO

import pytest
import yaml

from dataforge.database_maintenance import backup, restore_backup
from dataforge.migration import engine, service
from dataforge.migration.targets import LEGACY_DATABRICKS, WAREHOUSES
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

    def count(query, *args, **kwargs):
        lowered.append(query.selects[0].sql())
        return original(query, *args, **kwargs)

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


def test_sas_set_stack_requires_compatible_types_from_every_input():
    code = "data stacked; set raw.open raw.closed; keep id amount; run;"
    snapshot = {"sources": [{"id": "root", "path": "input.sas", "kind": "sas", "text": code,
                             "hash": engine.digest(code)}],
                "warehouse": "databricks", "catalog": "main", "schema": "migration"}
    plan, files = engine.convert(snapshot)
    assert "UNION ALL" in files["stacked"]["sql"]
    first, second = plan["outputs"]["stacked"]["inputs"]
    for row in plan["physical"].values():
        row["assumed_location"] = False
    snapshot["input_types"] = {first: {"id": "BIGINT", "amount": "DOUBLE"}, second: {"id": "INT"}}
    for amount in (None, "STRING", "DOUBLE"):
        if amount:
            snapshot["input_types"][second]["amount"] = amount
        report = engine.validate(snapshot, plan, files)
        if amount == "DOUBLE":
            assert report["tiers"]["stacked"] == "needs_investigation"
        else:
            assert report["tiers"]["stacked"] == "blocked"
            assert any(item["code"] == "sas_stack_schema" and "amount" in item["message"] for item in report["findings"])


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


def test_tsql_staging_requires_a_unique_earlier_writer_in_the_same_script():
    create = "SELECT 1 AS id INTO [#stage]"
    consume = "CREATE VIEW consumer AS WITH stage AS (SELECT 2 AS id) SELECT [#stage].id FROM [#stage];"
    for scripts, valid in [
        ([create + "\nGO -- next batch\n" + consume], True),
        ([create + ";", consume], False),
        ([create + ";" + consume + "INSERT INTO #stage SELECT 2;"], False),
        ([consume + create + ";"], False),
        ([create + "\nGO 2\n" + consume], False),
    ]:
        snapshot = {"sources": [{"id": str(i), "path": f"{i}.sql", "kind": "sql", "text": code,
                                 "hash": engine.digest(code), "dialect": "tsql"} for i, code in enumerate(scripts)],
                    "warehouse": "databricks", "catalog": "main", "schema": "migration"}
        plan, files = engine.convert(snapshot)
        assert not plan["physical"]
        assert sum(region["end"] - region["start"] for region in plan["regions"]) == sum(map(len, scripts))
        consumer = plan["outputs"]["consumer"]
        if valid:
            stage, = consumer["inputs"]
            assert plan["outputs"][stage]["materialization"] == "ephemeral"
            assert "INTO" not in files[stage]["sql"] and "#stage" not in files["consumer"]["sql"]
            assert f"{{{{ ref('{stage}') }}}}" in files["consumer"]["sql"]
        else:
            assert "consumer" not in files and "preceding SELECT INTO" in consumer["manual"]


def test_ordered_sas_requires_evidence_and_keeps_the_draft_revision_checked(tmp_path):
    code = ("data totals; set raw.orders; by account day; if first.account then total=0; total + amount; "
            "keep account day amount total; run;\nproc sort data=raw.orders out=survivors nodupkey; by account; run;\n"
            "data merged; merge raw.orders raw.status; by account; run;")
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace("Ordered SAS")
        project = service.create_project(store, workspace, "Ordered SAS", {
            "sources": [{"id": "s", "path": "s.sas", "kind": "sas", "text": code, "hash": engine.digest(code)}],
            "warehouse": "databricks", "catalog": "main", "schema": "migration",
        })
        pid = project["id"]
        base = service.convert(store, workspace, pid, project["revision"])
        project, _ = service.load(store, workspace, pid)
        plan = base["plan"]
        assert not base["files"]
        assert {plan["physical"][key]["relation"] for key in plan["outputs"]["merged"]["inputs"]} == {"raw.orders", "raw.status"}
        with pytest.raises(ValueError, match="Save the ordered SAS contract"):
            service.ordered_sas_proposal(project, base, "totals", ["day", "event_id"])
        for model, order, fragment in [("totals", ["day", "event_id"], "ROWS BETWEEN UNBOUNDED PRECEDING"),
                                       ("survivors", ["event_id DESC"], "ROW_NUMBER()")]:
            inputs = plan["outputs"][model]["inputs"]
            contracted = service.set_contract(store, workspace, pid, base["id"], model, inputs,
                                              "Preserve ordered output", "The confirmed priority sorts ties uniquely.")
            if model == "totals":
                with pytest.raises(ValueError, match="Preserve the SAS BY columns"):
                    service.ordered_sas_proposal(project, contracted, model, ["event_id"])
            proposal = service.ordered_sas_proposal(project, contracted, model, order)
            assert fragment in list(service.diffs(contracted, proposal))[0][1]
            assert model not in service.load(store, workspace, pid)[1]["files"]
            base = service.apply(store, workspace, pid, proposal)
            with pytest.raises(ValueError, match="stale"):
                service.apply(store, workspace, pid, proposal)
        assert service.report(project, base)["active"] == {}
        merged = service.set_contract(store, workspace, pid, base["id"], "merged", plan["outputs"]["merged"]["inputs"],
                                      "SAS match MERGE", "Match original BY groups", relations=["main.raw.sequence"])
        assert {merged["plan"]["physical"][key]["relation"] for key in merged["plan"]["outputs"]["merged"]["inputs"]} == {
            "raw.orders", "raw.status", "main.raw.sequence"}


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


def test_pilot_handoff_records_only_revision_bound_external_evidence(tmp_path):
    programs = {
        "report.sql": "CREATE VIEW staged AS SELECT 1 AS id, 10 AS amount; "
                      "CREATE VIEW result AS SELECT id, amount FROM staged;",
        "unrelated.sql": "CREATE PROCEDURE ignored() BEGIN SELECT 1; END;",
    }
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace("Pilot")
        project = service.create_project(store, workspace, "Pilot", {
            "sources": [{"id": path, "path": path, "kind": "sql", "hash": engine.digest(code), "text": code}
                        for path, code in programs.items()],
            "warehouse": "databricks", "catalog": "main", "schema": "migration",
        })
        pid = project["id"]
        base = service.convert(store, workspace, pid, project["revision"])
        reviewed = service.configure_validation(store, workspace, pid, base["id"], "result", {
            "not_null": ["id"], "unique": ["id"], "relationship": {"model": "staged", "column": "id", "field": "id"},
            "comparison": {"legacy": "legacy.report", "keys": ["id"], "totals": ["amount"], "tolerance": 0.01},
        })
        with pytest.raises(ValueError, match="all required"):
            service.bundle(store, workspace, pid, reviewed["id"], reviewed=True)
        data = service.bundle(store, workspace, pid, reviewed["id"], reviewed=True, pilot=["result"])
        with zipfile.ZipFile(BytesIO(data)) as bundle:
            handoff = json.loads(bundle.read("migration/manifest.json"))
            assert handoff["mode"] == "pilot" and handoff["included_models"] == ["result", "staged"]
            assert all(engine.digest(bundle.read(path)) == row["sha256"] for path, row in handoff["files"].items())
            assert "unrelated.sql" not in bundle.read("migration/coverage.json").decode()
            comparison, = json.loads(bundle.read("migration/reconciliation.json"))
            assert comparison["target"] == "main.migration.result" and comparison["status"] == "not_evaluated"
            reader = csv.DictReader(StringIO(bundle.read("migration/reconciliation-results.csv").decode()))
            result_columns = reader.fieldnames
            comparison_rows = {(row["check"], row["column"]): row for row in reader}
            assert set(comparison_rows) == {
                ("row_count", ""), ("null_counts", "id"), ("null_counts", "amount"),
                ("duplicate_keys", ""), ("column_sums", "amount"), ("matched_keys", ""),
                ("missing_keys", ""), ("extra_keys", ""), ("column_mismatches", "amount"),
            }
            assert comparison_rows["column_sums", "amount"]["comparison_id"] == comparison["comparison_id"]
            project_name = yaml.safe_load(bundle.read("dbt_project.yml"))["name"]
            configs = {model["name"]: model for model in yaml.safe_load(bundle.read("models/schema.yml"))["models"]}
            required, unique, relationship = configs["result"]["columns"][0]["data_tests"]
            assert "unique" in unique and "relationships" in relationship
            nodes = {f"model.{project_name}.{name}": {
                "original_file_path": f"models/{name}.sql", "raw_code": bundle.read(f"models/{name}.sql").decode().strip(),
                "database": "main", "schema": "migration", "alias": name, "config": model["config"],
                "depends_on": {"nodes": [f"model.{project_name}.staged"] if name == "result" else []},
            } for name, model in configs.items()}
        uid = f"model.{project_name}.result"
        test_name = required["not_null"]["name"]
        test_id = f"test.{project_name}.{test_name}.123"
        nodes[test_id] = {"name": test_name, "attached_node": uid, "test_metadata": {
            "name": "not_null", "kwargs": {"column_name": "id"},
        }}
        header = {"project_name": project_name, "adapter_type": "databricks",
                  "invocation_id": "77777777-1234-4321-ABCD-000000000000", "env": {"GRAVETRAIL_REVISION": reviewed["id"]},
                  "dbt_version": WAREHOUSES["databricks"].core_version}
        manifest = {"metadata": {**header, "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"},
                    "nodes": nodes}
        results = {"metadata": {**header, "dbt_schema_version": "https://schemas.getdbt.com/dbt/run-results/v6.json"},
                   "args": {"which": "build"}, "results": [
                       {"unique_id": uid, "status": "success", "compiled": True, "message": "synthetic secret"},
                       {"unique_id": test_id, "status": "fail", "failures": 1},
                   ]}

        def upload(revision=reviewed["id"]):
            return service.import_validation(store, workspace, pid, revision,
                                             json.dumps(manifest).encode(), json.dumps(results).encode())

        with pytest.raises(ValueError, match="revision"):
            upload(base["id"])
        saved_invocation = results["metadata"]["invocation_id"]
        results["metadata"]["invocation_id"] = "99999999-1234-4321-ABCD-000000000000"
        with pytest.raises(ValueError, match="invocation mismatch"):
            upload()
        results["metadata"]["invocation_id"] = saved_invocation
        saved_code = nodes[uid]["raw_code"]
        nodes[uid]["raw_code"] = "SELECT 9 AS id"
        with pytest.raises(ValueError, match="differs"):
            upload()
        nodes[uid]["raw_code"] = saved_code
        summary = upload()
        assert upload() == summary and service.validation_runs(store, workspace, pid) == [summary]
        assert summary["models"]["staged"] == {"tests": {}}
        assert summary["models"]["result"]["build"] == "success"
        assert summary["models"]["result"]["tests"][test_name] == "fail"
        assert summary["models"]["result"]["tests"][unique["unique"]["name"]] == "not observed"
        assert "synthetic secret" not in json.dumps(summary)
        assert service.report(*service.load(store, workspace, pid))["runtime_equivalence"] == "not_evaluated"
        with pytest.raises(ValueError, match="Different evidence"):
            results["results"][1]["status"] = "pass"
            upload()

        def record_comparison(revision=reviewed["id"]):
            results_csv = StringIO()
            writer = csv.DictWriter(results_csv, fieldnames=result_columns)
            writer.writeheader()
            writer.writerows(comparison_rows.values())
            return service.import_reconciliation(store, workspace, pid, revision, results_csv.getvalue().encode())

        comparison_rows["row_count", ""].update(legacy_value="100", target_value="100")
        count_row = comparison_rows["row_count", ""]
        count_row["comparison_id"] = "stale-plan"
        with pytest.raises(ValueError, match="comparison plan"):
            record_comparison()
        count_row["comparison_id"] = comparison["comparison_id"]
        partial = record_comparison()
        assert partial["models"]["result"]["status"] == "incomplete"
        comparison_rows["column_sums", "amount"].update(legacy_value="9999999999999999.1",
                                                         target_value="9999999999999999.11")
        comparison_rows["null_counts", "id"].update(legacy_value="101", target_value="0")
        with pytest.raises(ValueError, match="cannot exceed"):
            record_comparison()
        comparison_rows["null_counts", "id"]["legacy_value"] = "0"
        comparison_rows["null_counts", "amount"].update(legacy_value="0", target_value="0")
        comparison_rows["duplicate_keys", ""].update(legacy_value="1", target_value="1")
        duplicate = record_comparison()["models"]["result"]
        assert duplicate["status"] == "fail"
        assert next(row for row in duplicate["checks"] if row["check"] == "column_sums")["status"] == "pass"
        comparison_rows["duplicate_keys", ""].update(legacy_value="0", target_value="0")
        assert record_comparison()["models"]["result"]["status"] == "incomplete"
        comparison_rows["matched_keys", ""]["comparison_value"] = "100"
        comparison_rows["extra_keys", ""]["comparison_value"] = "0"
        comparison_rows["missing_keys", ""]["comparison_value"] = "1"
        with pytest.raises(ValueError, match="account for both row counts"):
            record_comparison()
        comparison_rows["missing_keys", ""]["comparison_value"] = "0"
        comparison_rows["column_mismatches", "amount"]["comparison_value"] = "2"
        swapped = record_comparison()["models"]["result"]
        assert swapped["status"] == "fail" and swapped["complete"]
        assert next(row for row in swapped["checks"] if row["check"] == "column_mismatches")["comparison"] == "2"
        comparison_rows["column_mismatches", "amount"]["comparison_value"] = "0"
        matched = record_comparison()
        assert matched["models"]["result"]["status"] == "pass"
        assert record_comparison() == matched
        comparison_rows["row_count", ""].update(legacy_value="0", target_value="0")
        comparison_rows["column_sums", "amount"].update(legacy_value="0", target_value="0")
        comparison_rows["matched_keys", ""]["comparison_value"] = "0"
        empty = record_comparison()["models"]["result"]
        assert empty["empty_sample"] and empty["status"] == "incomplete"
        next_revision = service.configure_validation(store, workspace, pid, reviewed["id"], "result", {
            "comparison": {"legacy": "legacy.report", "keys": ["id"], "totals": ["id"], "tolerance": 0},
        })
        with pytest.raises(ValueError, match="selected revision"):
            record_comparison(next_revision["id"])
        history = service.reconciliation_runs(store, workspace, pid)
        assert len(history) == 6 and {entry["revision"] for entry in history} == {reviewed["id"]}
        assert service.report(*service.load(store, workspace, pid))["runtime_equivalence"] == "not_evaluated"


def test_bulk_mappings_and_delta_merge_are_revision_checked(tmp_path):
    code = ("MERGE INTO legacy.next_values AS t USING main.legacy.rows AS s ON (t.id=s.id AND s.region=t.region) "
            "WHEN MATCHED THEN UPDATE SET t.value=s.value "
            "WHEN NOT MATCHED THEN INSERT (id,region,value) VALUES (s.id,s.region,s.value);")
    with closing(Store(tmp_path)) as store:
        workspace = store.create_workspace("Incremental")
        project = service.create_project(store, workspace, "Incremental", {
            "sources": [{"id": "s", "path": "s.sql", "kind": "sql", "text": code, "hash": engine.digest(code), "dialect": "tsql"}],
            "warehouse": "databricks", "catalog": "main", "schema": "migration", "profile": LEGACY_DATABRICKS.profile,
        })
        pid = project["id"]
        base = service.convert(store, workspace, pid, project["revision"])
        physical, = base["plan"]["physical"]
        assert base["plan"]["outputs"]["next_values"]["suggested_merge_keys"] == ["id", "region"]
        assert "MERGE" not in base["files"]["next_values"]["sql"]
        assert not service.report(*service.load(store, workspace, pid))["active"]
        with pytest.raises(ValueError, match="original MERGE predicate"):
            service.configure_validation(store, workspace, pid, base["id"], "next_values", {}, ["id"])
        with pytest.raises(ValueError, match="Confirm types"):
            service.configure_validation(store, workspace, pid, base["id"], "next_values", {}, ["id", "region"])
        mappings_csv = f"source,catalog,schema,identifier\n{physical},main,raw,accounts\n"
        with pytest.raises(ValueError, match="complete mapping"):
            service.read_source_mappings((mappings_csv + mappings_csv.splitlines()[1]).encode())
        mapped = service.revise_schemas(store, workspace, pid, base["id"], {
            "source_mappings": service.read_source_mappings(mappings_csv.encode()),
            "input_types": {physical: {"id": "INT", "region": "STRING", "value": "INT"}},
        })
        configured = service.configure_validation(store, workspace, pid, mapped["id"], "next_values", {
            "comparison": {"legacy": "legacy.next_values", "keys": ["id", "region"],
                           "columns": ["value"], "totals": ["value"], "tolerance": 1},
        }, ["id", "region"])
        with pytest.raises(ValueError, match="Migration changed"):
            service.configure_validation(store, workspace, pid, mapped["id"], "next_values", {})
        details = service.report(service.load(store, workspace, pid)[0], configured)
        assert not details["eligible"]
        findings = [item["id"] for item in details["findings"] if item["model"] == "next_values"]
        accepted = service.record_review(store, workspace, pid, configured["id"], "next_values", "Engineer", "Upsert reviewed", findings)
        with zipfile.ZipFile(BytesIO(service.bundle(store, workspace, pid, accepted["id"], reviewed=True))) as bundle:
            model, = yaml.safe_load(bundle.read("models/schema.yml"))["models"]
            assert model["config"]["materialized"] == "incremental" and model["config"]["unique_key"] == ["id", "region"]
            assert model["config"]["full_refresh"] is False
            assert b"dbt-core==1.10.13" in bundle.read("requirements.txt")
            assert b"identifier: accounts" in bundle.read("models/sources.yml")
            reader = csv.DictReader(StringIO(bundle.read("migration/reconciliation-results.csv").decode()))
            evidence = list(reader)
            fields = reader.fieldnames
        assert "input_snapshot_id" in fields
        assert {row["column"] for row in evidence if row["check"] == "column_mismatches"} == {"value"}

        def record_stages(stages, overrides=None):
            overrides = overrides or {}
            output = StringIO()
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            for row in evidence:
                stage, check = row["stage"], row["check"]
                if stage not in stages:
                    continue
                if check in {"row_count", "null_counts", "duplicate_keys", "column_sums"}:
                    value = {"row_count": 1, "column_sums": 10}.get(check, 0)
                    values = {"legacy_value": value, "target_value": value}
                    if check == "row_count":
                        values["input_snapshot_id"] = "batch-2026-11"
                else:
                    values = {"comparison_value": int(check == "matched_keys")}
                writer.writerow({**row, **values, **overrides.get((stage, check), {})})
            run = service.import_reconciliation(store, workspace, pid, accepted["id"], output.getvalue().encode())
            return run["models"]["next_values"]

        partial = record_stages({"initial_load"})
        assert partial["status"] == "incomplete" and not partial["complete"]
        assert partial["stages"]["initial_load"]["status"] == "pass"
        assert partial["stages"]["repeat_run"]["status"] == "incomplete"
        legacy_stages = {"initial_load", "repeat_run"}
        assert record_stages(legacy_stages)["status"] == "incomplete"
        all_stages = legacy_stages | {"initial_vs_repeat"}
        assert {row["stage"] for row in evidence} == all_stages
        complete = record_stages(all_stages)
        assert complete["status"] == "pass" and complete["complete"]
        assert complete["stages"]["initial_vs_repeat"]["status"] == "pass"
        assert record_stages(all_stages, {("repeat_run", "row_count"): {"input_snapshot_id": ""}})["status"] == "incomplete"
        for override in (
            {("repeat_run", "row_count"): {"input_snapshot_id": "another-batch"}},
            {("repeat_run", "column_sums"): {"legacy_value": 11}},
            {("repeat_run", "column_sums"): {"target_value": 11}},
        ):
            changed = record_stages(all_stages, override)
            assert changed["status"] == "fail"
            assert all(changed["stages"][stage]["status"] == "pass" for stage in legacy_stages)
            assert changed["stages"]["initial_vs_repeat"]["status"] == "fail"
        changed = record_stages(all_stages, {("initial_vs_repeat", "column_mismatches"): {"comparison_value": 1}})
        assert changed["status"] == "fail" and changed["complete"]
        mismatch = next(check for check in changed["checks"]
                        if check["stage"] == "initial_vs_repeat" and check["check"] == "column_mismatches")
        assert mismatch["column"] == "value" and mismatch["comparison"] == "1" and mismatch["status"] == "fail"
        replaced = record_stages(all_stages, {
            ("initial_vs_repeat", "matched_keys"): {"comparison_value": 0},
            ("initial_vs_repeat", "missing_keys"): {"comparison_value": 1},
            ("initial_vs_repeat", "extra_keys"): {"comparison_value": 1},
        })
        assert replaced["status"] == "fail" and replaced["complete"]
        assert {check["check"]: check["comparison"] for check in replaced["checks"]
                if check["stage"] == "initial_vs_repeat" and check["status"] == "fail"} == {
            "missing_keys": "1", "extra_keys": "1",
        }
        conditional = code.replace("WHEN MATCHED THEN UPDATE SET t.value=s.value", "WHEN MATCHED AND s.value IS NULL THEN DELETE")
        snapshot = {"warehouse": "databricks", "catalog": "main", "schema": "migration",
                    "sources": [{"id": "s", "path": "s.sql", "kind": "sql", "dialect": "tsql",
                                 "text": conditional, "hash": engine.digest(conditional)}]}
        plan, drafts = engine.convert(snapshot)
        assert not drafts and plan["outputs"]["next_values"]["critical"]
        assert [row["relation"] for row in plan["physical"].values()] == ["main.legacy.rows"]


def test_materialized_sql_reads_the_relation_version_at_its_statement():
    read = "CREATE OR REPLACE TABLE legacy.report AS SELECT id FROM main.legacy.state; "
    write = "CREATE OR REPLACE TABLE main.legacy.state AS SELECT 2 AS id; "
    for code, before in [(read + write, True), (write + read, False)]:
        snapshot = {"warehouse": "databricks", "catalog": "main", "schema": "migration",
                    "sources": [{"id": "s", "path": "s.sql", "kind": "sql", "dialect": "databricks",
                                 "text": code, "hash": engine.digest(code)}]}
        plan, files = engine.convert(snapshot)
        report = engine.validate(snapshot, plan, files)
        if before:
            key, = plan["outputs"]["report"]["inputs"]
            assert plan["physical"][key]["relation"] == "main.legacy.state"
            assert report["tiers"]["report"] == "blocked" and "source(" in files["report"]["sql"]
            plan["physical"][key].update(schema="archive", assumed_location=False)
            confirmed = engine.validate(snapshot, plan, files)
            assert confirmed["tiers"]["report"] == "needs_investigation"
            plan.update(version=6, physical={})
            plan["outputs"]["report"]["inputs"] = ["state"]
            old = "SELECT id FROM {{ ref('state') }} AS state"
            files["report"] = {"sql": old, "hash": engine.digest(old), "origin": "static"}
            report = engine.validate(snapshot, plan, files)
            assert not report["eligible"] and report["tiers"]["report"] == "blocked"
            assert any(row["code"] == "legacy_source_order" for row in report["findings"])
        else:
            assert plan["outputs"]["report"]["inputs"] == ["state"]
            assert report["active"]["report"] == "statically_qualified"


def test_sas_selection_uses_work_identity_and_requires_same_session():
    programs = ["data stage; set raw.values; keep id; run; data result; set work.stage; keep id; run;",
                "data other; set stage; keep id; run;"]
    snapshot = {"warehouse": "databricks", "catalog": "main", "schema": "migration",
                "sources": [{"id": str(i), "path": f"s{i}.sas", "kind": "sas", "text": code,
                             "hash": engine.digest(code)} for i, code in enumerate(programs)],
                "selected_outputs": ["work.result", "work.other"],
                "known_outputs": {"0": ["work.stage", "work.result"], "1": ["work.other"]}}
    plan, files = engine.convert(snapshot)
    assert set(plan["outputs"]) == {"stage", "result", "other"}
    assert set(files) == {"stage", "result"} and plan["outputs"]["result"]["inputs"] == ["stage"]
    assert not plan["outputs"]["other"]["inputs"] and "session" in plan["outputs"]["other"]["manual"]
    assert all(f["code"] != "unmatched_selection" for f in engine.validate(snapshot, plan, files)["findings"])
    code = "data result; set raw.customers; keep id; run;"
    snapshot["sources"].append({"id": "2", "path": "customers.sas", "kind": "sas", "text": code,
                                "hash": engine.digest(code), "selected": False})
    plan, files = engine.convert(snapshot)
    assert set(files) == {"stage", "result"}
    snapshot["sources"][-1]["selected"] = True
    plan, files = engine.convert(snapshot)
    report = engine.validate(snapshot, plan, files)
    assert any(row["code"] == "ambiguous_work_selection" for row in report["findings"])


def test_target_grain_using_bindings_and_set_types():
    code = ("CREATE VIEW x AS SELECT 1 AS id, 5 AS amount; CREATE VIEW y AS SELECT 2 AS id; "
            "CREATE VIEW invalid_group AS SELECT id, COUNT(*) AS n FROM x; "
            "CREATE VIEW invalid_key AS SELECT id, COUNT(*) AS n FROM x GROUP BY id + 1; "
            "CREATE VIEW invalid_bucket AS SELECT id + 1 AS i, COUNT(*) AS n FROM x GROUP BY id + 2; "
            "CREATE VIEW invalid_group_agg AS SELECT COUNT(*) AS n FROM x GROUP BY COUNT(*); "
            "CREATE VIEW invalid_star AS SELECT *, COUNT(*) AS n FROM x; "
            "CREATE VIEW valid_group AS SELECT x.id, COUNT(*) AS n FROM x GROUP BY id; "
            "CREATE VIEW same_bucket AS SELECT id + 1 AS i, COUNT(*) AS n FROM x GROUP BY 1 + x.id; "
            "CREATE VIEW valid_window AS SELECT id, SUM(amount) OVER () AS n FROM x; "
            "CREATE VIEW joined AS SELECT id FROM x FULL JOIN y USING (id); "
            "CREATE VIEW semi AS SELECT id FROM x LEFT SEMI JOIN y ON x.id=y.id; "
            "CREATE VIEW anti AS SELECT id FROM x LEFT ANTI JOIN (SELECT id FROM y) rhs USING (id); "
            "CREATE VIEW leaked_rhs AS SELECT y.id FROM x LEFT SEMI JOIN y ON x.id=y.id; "
            "CREATE VIEW widened AS SELECT 1 AS n UNION ALL SELECT COUNT(*) AS n FROM x; "
            "CREATE VIEW mixed AS SELECT 1 AS n UNION ALL SELECT 'unknown' AS n;")
    snapshot = {"warehouse": "databricks", "catalog": "main", "schema": "migration",
                "sources": [{"id": "s", "path": "s.sql", "kind": "sql", "dialect": "databricks",
                             "text": code, "hash": engine.digest(code)}]}
    plan, files = engine.convert(snapshot)
    report = engine.validate(snapshot, plan, files)
    assert {f["model"] for f in report["findings"] if f["code"] == "target_aggregation"} == {
        "invalid_group", "invalid_key", "invalid_bucket", "invalid_star", "invalid_group_agg"}
    assert {"valid_group", "same_bucket"} <= report["active"].keys()
    assert all(report["tiers"][key] != "blocked" for key in ("valid_window", "semi", "anti"))
    assert report["tiers"]["leaked_rhs"] == "blocked"
    assert plan["outputs"]["semi"]["inputs"] == ["x", "y"]
    assert {edge["source"] for edge in report["lineage"]["columns"] if edge["model"] == "semi"} == {"x"}
    assert {edge["source"] for edge in report["lineage"]["columns"] if edge["model"] == "joined"} == {"x", "y"}
    assert report["tiers"]["joined"] != "blocked"
    assert report["schemas"]["widened"]["n"]["target_type"] == "BIGINT"
    assert report["schemas"]["mixed"]["n"]["provenance"] == "assumed_string"
