"""CLI and MCP migration parity across one pinned workspace and revision."""

import asyncio
import base64
import hashlib
import json
import zipfile
from contextlib import closing
from io import BytesIO

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server, http_app
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.ingestion import Importer
from dataforge.llm import Profile
from dataforge.migration import assistance, engine, service, workflow
from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
from dataforge.store import Store


def test_cli_migration_is_reviewable_and_exportable_over_mcp(tmp_path, monkeypatch):
    home = tmp_path / "home"
    with closing(Store(home)) as store:
        w = store.create_workspace("Migration parity")
        Importer(store, w).files([("pipeline.sql", b"CREATE VIEW first AS SELECT 1 AS id; CREATE VIEW second AS SELECT id FROM first;")],
                                 {".sql"})
    setup = tmp_path / "setup.json"
    setup.write_text(json.dumps({"schema": "review"}), encoding="utf-8")
    runner = CliRunner()
    prefix = ["--home", str(home), "--json", "--allow-write", "migration"]

    def cli(*args):
        response = runner.invoke(app, [*prefix, *args, "-w", w])
        assert response.exit_code == 0, response.output
        return json.loads(response.stdout)

    preview = cli("preview", "Pilot", str(setup))
    project = cli("create", "Pilot", str(setup), "--expected-pin", preview["pin"])
    pid = project["id"]
    assert cli("list")["items"][0]["revision"] == project["revision"]
    job = cli("convert", pid, "--revision", project["revision"])
    assert job["status"] == "completed"
    base = job["result"]["revision_id"]

    monkeypatch.setenv("DATAFORGE_MCP_TOKEN", "migration-test-" + "x" * 40)
    with closing(Store(home)) as store, closing(AgentService(store, AccessPolicy(allow_write=True, workspaces=(w,)))) as agent:
        server = create_server(agent)
        application = http_app(server, agent.policy)

        async def check():
            async with server.session_manager.run():
                headers = {"Authorization": "Bearer migration-test-" + "x" * 40}
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), headers=headers) as client:
                    async with streamable_http_client("http://127.0.0.1:8765/mcp", http_client=client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()

                            async def call(tool, **args):
                                result = await session.call_tool(tool, {"workspace_id": w, **args})
                                return result.structuredContent

                            scope = {"project_id": pid, "revision_id": base}
                            edges = await call("inspect_migration_revision", **scope, view="lineage")
                            assert [(row["source"], row["target"]) for row in edges["items"]] == [("first", "second")]
                            artifact = await call("inspect_migration_revision", **scope, view="artifact", item="second", anchor="source")
                            assert "CREATE VIEW second" in artifact["text"]
                            patch = await call("preview_migration_edit", **scope, arguments={
                                "replacements": {"first": "SELECT 2 AS id"}, "rationale": "Use the confirmed ID"})
                            assert "+SELECT 2 AS id" in patch["diffs"]["first"]
                            args = {"operation": "apply", "arguments": {"proposal": patch["proposal"], "expected_pin": patch["pin"]}}
                            changed = await call("update_migration_revision", **scope, **args)
                            stale = await call("update_migration_revision", **scope, **args)
                            assert stale["error"]["code"] == "conflict"
                            export = await call("export_migration_bundle", project_id=pid, revision_id=changed["revision_id"])
                            payload = bytearray()
                            while len(payload) < export["bytes"]:
                                data = await call("get_export", artifact_id=export["artifact_id"], offset=len(payload))
                                chunk = base64.b64decode(data["data"])
                                assert chunk
                                payload.extend(chunk)
                            assert hashlib.sha256(payload).hexdigest() == export["sha256"]
                            with zipfile.ZipFile(BytesIO(payload)) as bundle:
                                assert b"SELECT 2 AS id" in bundle.read("review/first.sql.txt")
                            store.set_setting(w, "agent_access", {"allow_source": False})
                            denied = await call("get_export", artifact_id=export["artifact_id"])
                            assert denied["error"]["code"] == "forbidden"
                            summary = await call("inspect_migration_revision", **scope)
                            assert "SELECT" not in json.dumps(summary) and summary["revision_id"] == base

        asyncio.run(check())


def test_migration_ai_requires_exact_disclosure_and_launch_grants(tmp_path):
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace("Migration provider parity")
        Importer(store, w).files([("flow.sql", b"CREATE VIEW result AS SELECT 1 AS id;")], {".sql"})
        profile = Profile(provider="LM Studio", base_url="http://localhost:1234/v1", model="migration",
                          source_limit_policy="token_capacity", max_tokens=2048)
        profile = profile.model_copy(update={"model_capabilities": bind_capabilities(
            ModelCapabilities(context_tokens=32_000, output_tokens=2048, source="manual"), profile)})
        store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["local", w, "Local", profile.model_dump_json()])
        policy = AccessPolicy(allow_write=True, workspaces=(w,), allow_llm=True, allowed_llm_origins=(profile.base_url,))
        with closing(AgentService(store, policy)) as agent:
            preview = agent.call("migration_preview", w, name="Scoped", setup={})
            project = agent.call("migration_create", w, name="Scoped", setup={}, expected_pin=preview["pin"])
            job = agent.call("migration_convert", w, project_id=project["id"], expected_revision=project["revision"])
            agent.jobs.wait(job["job_id"], w)
            base = agent.job_status(w, job["job_id"])["result"]["revision_id"]
            args = {"project_id": project["id"], "revision_id": base, "profile_id": "local", "models": ["result"],
                    "purpose": "explain", "message": "Describe the output"}
            requests = []

            def transport(request):
                requests.append(request)
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                    "answer": "A literal ID", "citations": ["r1"], "edits": {}})}, "finish_reason": "stop"}]})

            agent.provider_transport = httpx.MockTransport(transport)
            pin = agent.call("migration_ai_preview", w, **args)["pin"]
            assert not requests
            with closing(AgentService(store, AccessPolicy(allow_write=True, allow_llm=True))) as denied:
                denied.provider_transport = agent.provider_transport
                with pytest.raises(AgentError) as error:
                    denied.call("migration_ai_request", w, **args, expected_pin=pin)
                assert error.value.code == "network_not_allowed"
            with pytest.raises(AgentError):
                agent.call("migration_ai_request", w, **{**args, "message": "Different disclosure"}, expected_pin=pin)
            assert not requests
            reply = agent.call("migration_ai_request", w, **args, expected_pin=pin)
            assert len(requests) == 1 and reply["answer"] == "A literal ID" and "proposal" not in reply
            assert agent.call("migration_inspect", w, project_id=project["id"], view="ai_responses")["total"] == 0


@pytest.mark.parametrize("optimization_finish", ["stop", "length"])
def test_file_guided_ai_migration_keeps_both_outputs_and_requires_review(tmp_path, optimization_finish):
    original = ("CREATE VIEW staged AS WITH t AS (SELECT 1 AS id) SELECT id FROM t;\n"
                "CREATE VIEW result AS SELECT id FROM staged;\n")
    staged = "WITH t AS (SELECT 1 AS id) SELECT id FROM t"
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace("Guided AI")
        store.set_setting(w, "agent_access", {"max_chars": 100_000})
        Importer(store, w).files([("flow.sql", original.encode())], {".sql"})
        profile = Profile(provider="LM Studio", base_url="http://localhost:1234/v1", model="migration",
                          source_limit_policy="token_capacity", max_tokens=2048)
        profile = profile.model_copy(update={"model_capabilities": bind_capabilities(
            ModelCapabilities(context_tokens=32_000, output_tokens=2048, source="manual"), profile)})
        store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["local", w, "Local", profile.model_dump_json()])
        policy = AccessPolicy(allow_write=True, workspaces=(w,), allow_llm=True, allowed_llm_origins=(profile.base_url,))
        with closing(AgentService(store, policy)) as agent:
            plan = agent.call("migration_preview", w, name="Guided", setup={})
            project = agent.call("migration_create", w, name="Guided", setup={}, expected_pin=plan["pin"])
            pid = project["id"]
            job = agent.call("migration_convert", w, project_id=pid, expected_revision=project["revision"], plan_only=True)
            agent.jobs.wait(job["job_id"], w)
            base = agent.job_status(w, job["job_id"])["result"]["revision_id"]
            assert service.load(store, w, pid)[1]["files"] == {}
            files = agent.call("migration_inspect", w, project_id=pid, view="workflow")["items"]
            assert len(files) == 1 and files[0]["models"] == ["staged", "result"]
            source = files[0]["source_id"]
            scope = {"project_id": pid, "revision_id": base, "profile_id": "local", "source_id": source}
            disclosures = []
            response = {}

            def transport(request):
                disclosure = json.loads(json.loads(request.content)["messages"][-1]["content"])
                disclosures.append(disclosure)
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(response)},
                    "finish_reason": optimization_finish if disclosure["source_file"]["stage"] == "optimize" else "stop"}]})

            agent.provider_transport = httpx.MockTransport(transport)

            def preview(stage, **kwargs):
                return agent.call("migration_stage_preview", w, {"max_chars": 100_000},
                                  **scope, stage=stage, **kwargs)

            def run(stage, pin, **kwargs):
                return agent.call("migration_stage_request", w, **scope, stage=stage, expected_pin=pin, **kwargs)

            with pytest.raises(AgentError):
                preview("validate")
            pure = preview("convert")
            assert "static_reference" not in pure["body"]
            assert preview("convert", static_reference=True)["body"]["static_reference"]["staged"]
            parts = pure["body"]["source_file"]["regions"]
            assert "".join(region["original"] for region in parts) == original
            anchors = {output["model"]: output["span"]["id"] for output in pure["body"]["outputs"]}
            response.update(answer="Two models translated", citations=[],
                            edits={"staged": f"CREATE VIEW staged AS {staged};",
                                   "result": "CREATE VIEW result AS SELECT id FROM staged;"})
            with pytest.raises(AgentError):
                run("convert", pure["pin"], feedback="Different disclosure")
            assert not disclosures
            run("convert", pure["pin"])
            assert len(disclosures) == 1
            assert service.load(store, w, pid)[1]["files"] == {}

            validation = preview("validate")
            drafts = {item["model"]: item["generated"] for item in validation["body"]["outputs"]}
            assert all(drafts.values()) and "{{ ref('staged') }}" in drafts["result"]
            assert all("CREATE VIEW" not in sql for sql in drafts.values())
            correction = preview("convert", feedback="Keep the same behavior.")
            response["edits"] = drafts
            run("convert", correction["pin"], feedback="Keep the same behavior.")
            validation = preview("validate")
            assert {item["model"]: item["generated"] for item in validation["body"]["outputs"]} == drafts
            recovery = preview("convert", static_reference=True)
            response["edits"] = {"staged": drafts["staged"], "result": "SELECT id FROM {{ ref('result') }}"}
            run("convert", recovery["pin"], static_reference=True)
            checkpoint = agent.call("migration_inspect", w, {"max_chars": 100_000}, project_id=pid,
                                    view="workflow", item=source)["workflow"]
            assert checkpoint["stages"]["convert"]["reference_recovered"] == ["result"]
            validation = preview("validate")
            assert {item["model"]: item["generated"] for item in validation["body"]["outputs"]} == drafts
            response.update(answer="Check the source row contract", edits={}, coverage={
                anchors["staged"]: {"status": "accounted", "detail": "The literal ID is carried through the CTE."}
            })
            with pytest.raises(AgentError):
                run("validate", validation["pin"])
            response["coverage"][anchors["result"]] = {"status": "uncertain", "detail": "Confirm the final output grain."}
            run("validate", validation["pin"])

            optimization = preview("optimize")
            response.pop("coverage")
            response.update(answer="Replace the literal", edits={"staged": drafts["staged"].replace("1 AS id", "2 AS id")})
            outcome = run("optimize", optimization["pin"])
            if optimization_finish == "length":
                assert outcome["status"] == "resize" and outcome["next_size"] == 1
                first = preview("optimize")
                assert first["body"]["source_file"]["part"]["from"] == 1
                assert run("optimize", first["pin"])["status"] == "partial"
                optimization = preview("optimize")
                assert optimization["body"]["source_file"]["part"]["from"] == 2
                outcome = run("optimize", optimization["pin"])
            assert outcome["status"] == "rejected"
            reviewed = agent.call("migration_inspect", w, {"max_chars": 100_000}, project_id=pid,
                                  view="workflow", item=source)
            assert reviewed["assessment"]["checks"] and not reviewed["assessment"]["optimized"]
            assert reviewed["proposal"]["edits"]["staged"]["sql"] == drafts["staged"]
            assert set(reviewed["diffs"]) == {"staged", "result"}
            assert agent.call("migration_inspect", w, {"max_chars": 100_000}, project_id=pid,
                              view="workflow", item=source)["proposal"]["id"] == reviewed["proposal"]["id"]
            arguments = {"source_id": source, "expected_pin": reviewed["pin"]}
            changed = agent.call("migration_change", w, project_id=pid, revision_id=base,
                                 operation="apply_source_draft", arguments=arguments)["revision_id"]
            with pytest.raises(AgentError):
                agent.call("migration_change", w, project_id=pid, revision_id=base,
                           operation="apply_source_draft", arguments=arguments)
            current, revision = service.load(store, w, pid)
            assert revision["id"] == changed and set(revision["files"]) == {"staged", "result"}
            assert set(service.report(current, revision)["tiers"].values()) <= {"needs_investigation", "blocked"}
            assert assistance.responses(store, w, pid) == []
            assert any(row["message"] == "Confirm the final output grain."
                       for row in service.report(current, revision)["findings"])
            lesson_id = assistance.save_lesson(store, w, pid, changed, {
                "kind": "sql", "pattern": "WITH t AS", "guidance": "Preserve the local CTE.",
                "example": staged, "counterexample": "SELECT id FROM t", "owner": "engineer",
            }, "staged")
            scope["revision_id"] = changed
            assert [rule["id"] for rule in preview("convert")["body"]["lessons"]] == [lesson_id]
            with zipfile.ZipFile(BytesIO(service.bundle(
                    store, w, pid, changed, image_format="svg", include_sources=True))) as bundle:
                assert bundle.read("migration/original-sources/flow.sql.txt").decode() == original
                assert "migration/lineage.svg" in bundle.namelist()
                assert "migration/ai-source-review.json" in bundle.namelist()
                assert b"Confirm the final output grain." in bundle.read("review/result.sql.txt")


def test_large_source_resumes_after_restart_and_keeps_unresolved_parts_reviewable(tmp_path):
    large = "\n".join(f"CREATE VIEW m{i:02d} AS SELECT id FROM seed;" for i in range(51))
    large += "\nCREATE VIEW oversized AS SELECT 1 AS id /* " + ("source context " * 2_000) + "*/;"
    bodies = {"parent": "CREATE VIEW seed AS SELECT 1 AS id;", "large": large}
    snapshot = {"warehouse": "databricks", "catalog": "main", "schema": "migration", "sources": [
        {"id": key, "path": key + ".sql", "kind": "sql", "text": sql, "hash": engine.digest(sql)}
        for key, sql in bodies.items()]}
    profile = Profile(provider="LM Studio", base_url="http://localhost:1234/v1", model="migration",
                      source_limit_policy="explicit", source_disclosure_chars=10_000, max_tokens=2048)
    profile = profile.model_copy(update={"model_capabilities": bind_capabilities(
        ModelCapabilities(context_tokens=64_000, output_tokens=2048, source="manual"), profile)})
    calls = []

    def complete(request):
        payload = json.loads(json.loads(request.content)["messages"][-1]["content"])
        file = payload["source_file"]
        calls.append((file["stage"], file["part"]["from"]))
        response = {"answer": "Part checked.", "citations": [], "edits": {}}
        if file["stage"] == "convert":
            assert all(output["model"] != "oversized" for output in payload["outputs"])
            response["edits"] = {row["model"]: "SELECT id FROM {{ ref('seed') }}" for row in payload["outputs"]}
        else:
            response["coverage"] = {region: {"status": "accounted", "detail": "Original ref and column are present."}
                                    for region in file["validate_regions"]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(response)}, "finish_reason": "stop"}]})

    transport = httpx.MockTransport(complete)
    with closing(Store(tmp_path)) as store:
        w = store.create_workspace("Large migration")
        store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["local", w, "Local", profile.model_dump_json()])
        project = service.create_project(store, w, "Large", snapshot)
        pid = project["id"]
        planned = service.convert(store, w, pid, project["revision"], plan_only=True)
        base = service.apply(store, w, pid, service.propose(planned, {"seed": "SELECT 1 AS id"}, "Preserve seed"))
        args = (w, pid, base["id"], "local", "large")
        first = workflow.preview(store, *args, "convert")
        assert 0 < len(first["scope"]) <= 50
        assert workflow.run(store, *args, "convert", first["pin"], transport=transport)["status"] == "partial"
        pending = workflow.preview(store, *args, "convert")

    def timeout(request):
        raise httpx.ReadTimeout("simulated interruption", request=request)

    with closing(Store(tmp_path)) as store:
        current, _ = service.load(store, w, pid)
        assert workflow.resume_source(store, w, current, base) == "large"
        resumed = workflow.preview(store, *args, "convert")
        assert resumed["pin"] == pending["pin"]
        assert resumed["body"]["source_file"]["part"]["from"] == len(first["scope"]) + 1
        with pytest.raises(ValueError, match="attempt was recorded"):
            workflow.run(store, *args, "convert", resumed["pin"], transport=httpx.MockTransport(timeout))
        for stage in ("convert", "validate"):
            for _ in range(12):
                preview = workflow.preview(store, *args, stage)
                result = workflow.run(store, *args, stage, preview["pin"], transport=transport)
                if result.get("status") != "partial":
                    break
            else:
                pytest.fail("A completed part did not advance the saved stage")
        assert calls.count(("convert", 1)) == 1
        assert set(service.load(store, w, pid)[1]["files"]) == {"seed"}
        workflow.skip_optimization(store, w, pid, base["id"], "large")
        proposal, receipt, pin = workflow.review(store, w, pid, base["id"], "large")
        assert len(proposal["edits"]) == 51 and receipt["unresolved_outputs"] == ["oversized"]
        assert len(receipt["coverage"]) == 52
        assert any(item["status"] == "gap" and "disclosure limit" in item.get("ai_detail", "")
                   for item in receipt["coverage"].values())
        revision = workflow.apply(store, w, pid, base["id"], "large", pin)
        pending = workflow.preview(store, w, pid, revision["id"], "local", "large", "convert")
        assert pending["scope"] == ["oversized"] and pending["request"] is None
        assert engine.source_review_status(revision) == {"large": "unresolved"}
        findings_only = {**revision, "settings": {**revision["settings"], "ai_source_reviews": {
            "large": {**receipt, "files": {}}}}}
        assert engine.source_review_status(findings_only) == {"large": "unresolved"}
        changed = service.apply(store, w, pid, service.propose(revision, {"seed": "SELECT 2 AS id"}, "Update seed"))
        current, _ = service.load(store, w, pid)
        state = workflow.state(store, w, current, changed, "large")
        assert state["assessment_status"] == "stale" and not state["applied"] and state["next"] == "convert"
