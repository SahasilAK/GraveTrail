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
