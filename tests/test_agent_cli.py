import json
import subprocess
import sys

from typer.testing import CliRunner

from dataforge.cli import app


def test_cli_standalone_help_workspace_and_errors(tmp_path):
    result = subprocess.run([sys.executable, "-m", "dataforge.cli", "--help"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and "workspace" in result.stdout
    runner = CliRunner()
    args = ["--home", str(tmp_path), "--json"]
    denied = runner.invoke(app, [*args, "workspace", "create", "demo"])
    assert denied.exit_code == 3 and json.loads(denied.stdout)["error"]["code"] == "forbidden"
    created = runner.invoke(app, [*args, "--allow-write", "workspace", "create", "demo"])
    assert created.exit_code == 0, created.stdout
    listed = runner.invoke(app, [*args, "workspace", "list"])
    assert json.loads(listed.stdout)["items"][0]["name"] == "demo"


def test_cli_import_build_background_status_and_export(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "flow.sql").write_text("create table pub.kpi as select id from raw.orders;", encoding="utf-8")
    runner = CliRunner()
    args = ["--home", str(tmp_path / "home"), "--json", "--allow-write", "--allowed-root", str(inputs)]
    created = runner.invoke(app, [*args, "workspace", "create", "workflow"])
    w = json.loads(created.stdout)["workspace_id"]
    imported = runner.invoke(app, [*args, "ingest", str(inputs), "--workspace", w])
    assert imported.exit_code == 0, imported.stdout
    assert json.loads(imported.stdout)["result"]["accepted"] == 1
    built = runner.invoke(app, [*args, "lineage", "build", "--workspace", w, "--background"])
    assert built.exit_code == 0, built.stdout
    job_id = json.loads(built.stdout)["job_id"]
    finished = runner.invoke(app, [*args, "jobs", "status", job_id, "--workspace", w, "--wait"])
    assert finished.exit_code == 0, finished.stdout
    assert json.loads(finished.stdout)["status"] == "completed"
    found = runner.invoke(app, [*args, "lineage", "upstream", "pub.kpi", "--workspace", w])
    assert json.loads(found.stdout)["items"][0]["name"] == "raw.orders"
    exported = runner.invoke(app, [*args, "export", "lineage", "pub.kpi", "--workspace", w])
    assert json.loads(exported.stdout)["result_id"]


def test_cli_jobs_obey_revocation_and_budget(tmp_path):
    from dataforge.agent.jobs import Jobs
    from dataforge.store import Store

    store = Store(tmp_path)
    w = store.create_workspace("jobs")
    jobs = Jobs(tmp_path)
    record = jobs.create(w, "analyze")
    record.update(status="completed", result={"unbounded": "x" * 2000})
    jobs.write(record)
    store.set_setting(w, "agent_access", {"max_chars": 512})
    store.close()
    runner = CliRunner()
    args = ["--home", str(tmp_path), "--json", "jobs", "status", record["job_id"], "--workspace", w]
    result = runner.invoke(app, args)
    assert result.exit_code == 2 and json.loads(result.stdout)["error"]["code"] == "budget_too_small"
    store = Store(tmp_path)
    store.set_setting(w, "agent_access", {"enabled": False})
    store.close()
    result = runner.invoke(app, args)
    assert result.exit_code == 3
    jobs.close()

