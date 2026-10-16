import json

import pytest

from dataforge.agent.contracts import AccessPolicy, AgentError, QueryOptions
from dataforge.agent.service import AgentService
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def engine(tmp_path):
    store = Store(tmp_path / "home")
    w = store.create_workspace("Agent fixture")
    Importer(store, w).files([
        ("orders.sql", b"create table stage.orders as select id, amount from raw.orders;\n"
         b"create table pub.all_kpis as select id from stage.orders;"),
        ("other.sql", b"create table other.orders as select id from raw.other;"),
        ("step.sas", b"data work.step; set raw.customers; run;\ndata pub.customers; set work.step; run;"),
        ("input.csv", b"id,amount\n1,20\n"),
    ], {".sql", ".sas", ".csv"})
    analyze(store, w)
    service = AgentService(store, AccessPolicy(allow_write=True))
    yield service, store, w
    service.close()
    store.close()


def test_lineage_columns_evidence_and_stored_reuse(engine, monkeypatch):
    service, store, w = engine
    monkeypatch.setattr("dataforge.services.analyze", lambda *a, **k: pytest.fail("query reparsed"))
    summary = service.call("lineage", w, asset="pub.all_kpis")
    assert {i["name"] for i in summary["items"]} == {"stage.orders", "raw.orders"}
    assert summary["complete"] and summary["analysis_current"]
    assert "select" not in json.dumps(summary).lower()
    detailed = service.call("lineage", w, asset="pub.all_kpis", options={"detail_level": "detailed"})
    assert detailed["items"][0]["relationships"]
    assert "select" in json.dumps(detailed).lower()
    columns = service.call("columns", w, asset="raw.orders")
    assert {c["column_name"] for c in columns["items"]} == {"id", "amount"}
    sid = store.edges(w)[0]["statement_id"]
    evidence = service.call("source", w, statement_id=sid)
    assert evidence["items"][0]["code"]


def test_pagination_depth_budget_and_ambiguity(engine):
    service, _, w = engine
    first = service.call("assets", w, options={"limit": 2})
    second = service.call("assets", w, options={"limit": 2, "cursor": first["next_cursor"]})
    assert not first["complete"] and first["next_cursor"]
    assert {i["asset_id"] for i in first["items"]}.isdisjoint(i["asset_id"] for i in second["items"])
    with pytest.raises(AgentError, match="ambiguous") as exc:
        service.call("lineage", w, asset="orders")
    assert len(exc.value.details["candidates"]) >= 3
    depth = service.call("lineage", w, asset="pub.all_kpis", options={"max_depth": 1})
    assert not depth["complete"] and "depth" in depth["boundaries"]
    page = service.call("lineage", w, asset="pub.all_kpis", options={"max_chars": 1000})
    assert len(json.dumps(page, ensure_ascii=False, separators=(",", ":"))) <= 1000
    with pytest.raises(ValueError):
        QueryOptions(max_chars=1000001)


def test_scope_permissions_and_cross_workspace_ids(engine):
    service, store, w = engine
    other = store.create_workspace("Other")
    restricted = AgentService(store, AccessPolicy(workspaces=(w,)))
    assert restricted.call("workspaces")["total"] == 1
    with pytest.raises(AgentError):
        restricted.call("summary", other)
    with pytest.raises(AgentError):
        restricted.call("analyze", w)
    fid = store.files(w)[0]["file_id"]
    with pytest.raises(AgentError):
        service.call("source", other, file_id=fid, start_line=1, end_line=2)
    store.set_setting(w, "agent_access", {"enabled": False})
    with pytest.raises(AgentError):
        service.call("assets", w)
    restricted.close()


def test_jobs_cache_and_stale_queries(engine):
    service, store, w = engine
    job = service.call("analyze", w)
    assert job["job_id"]
    done = service.jobs.wait(job["job_id"], w, timeout=20)
    assert done["status"] == "completed"
    assert done["result"]["cached"] == 4
    Importer(store, w).files([("new.sql", b"select id from new.source;")], {".sql"})
    assert not service.call("lineage", w, asset="pub.all_kpis")["analysis_current"]


def test_export_and_import_path_restrictions(engine, tmp_path):
    service, _, w = engine
    with pytest.raises(AgentError):
        service.call("ingest", w, path=str(tmp_path), extensions=["sql"])
    exported = service.call("export", w, asset="pub.all_kpis", format="json")
    assert exported["result_id"] and exported["bytes"] > 0
    assert "code" not in json.loads((service.store.home / exported["path"]).read_text())
    with pytest.raises(AgentError):
        service.call("source", w, file_id="../secret", full=True)


def test_settings_change_marks_analysis_stale_and_cursor_invalid(engine):
    service, store, w = engine
    first = service.call("assets", w, options={"limit": 1})
    store.set_setting(w, "case_sensitive", True)
    assert not service.call("lineage", w, asset="pub.all_kpis")["analysis_current"]
    Importer(store, w).files([("changed.sql", b"create table new.x as select id from raw.x;")], {".sql"})
    with pytest.raises(AgentError, match="Cursor"):
        service.call("assets", w, options={"cursor": first["next_cursor"]})


def test_source_opt_in_revocation_and_literal_search(engine):
    service, store, w = engine
    fid = store.files(w)[0]["file_id"]
    with pytest.raises(AgentError, match="start_line"):
        service.call("source", w, file_id=fid)
    explicit = service.call("source", w, file_id=fid, start_line=1, end_line=1)
    assert explicit["items"][0]["start_line"] == explicit["items"][0]["end_line"] == 1
    assert "code" not in json.dumps(service.call("search_code", w, query="select"))
    store.set_setting(w, "agent_access", {"allow_source": False, "allow_write": False})
    standard = service.call("columns", w, asset="raw.orders", options={"detail_level": "standard"})
    assert all("expression" not in row for row in standard["items"])
    for action, arguments in [("source", {"file_id": fid, "full": True}), ("analyze", {}),
                              ("lineage", {"asset": "pub.all_kpis", "options": {"detail_level": "detailed"}})]:
        with pytest.raises(AgentError):
            service.call(action, w, **arguments)


def test_batch_aggregate_limits_and_compact_size(engine, monkeypatch):
    service, _, w = engine
    import socket
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("unexpected network"))
    result = service.call("batch", w, assets=["pub.all_kpis", "pub.customers"], options={"max_items": 2})
    assert sum(r.get("count", 0) for r in result["results"]) <= 2
    assert not result["complete"] and result["remaining_assets"]
    small = service.call("lineage", w, asset="pub.all_kpis")
    large = service.call("lineage", w, asset="pub.all_kpis", options={"detail_level": "detailed"})
    assert len(json.dumps(small)) < len(json.dumps(large)) / 2


def test_job_failures_interruption_and_scope(engine):
    service, store, w = engine
    job = service.jobs.start(w, "analyze", lambda _: (_ for _ in ()).throw(ValueError("sensitive detail")))
    result = service.jobs.wait(job["job_id"], w, 10)
    assert result["status"] == "failed" and "sensitive detail" not in json.dumps(result)
    with pytest.raises(AgentError):
        service.jobs.read(job["job_id"], store.create_workspace("other"))
    record = service.jobs.create(w, "analyze")
    record["updated_at"] = 1
    service.jobs.write(record)
    assert service.jobs.read(record["job_id"], w)["status"] == "interrupted"


def test_job_poll_does_not_wait_for_import_transaction_and_respects_revocation(engine):
    import threading
    import time

    from dataforge.agent.contracts import AgentSettings

    service, store, w = engine
    record = service.jobs.create(w, "ingest")
    entered, release = threading.Event(), threading.Event()

    def transaction():
        with store.transaction():
            entered.set()
            release.wait(5)

    thread = threading.Thread(target=transaction)
    thread.start()
    assert entered.wait(5)
    try:
        start = time.monotonic()
        result = service.call("job", w, job_id=record["job_id"])
        assert result["status"] == "queued" and time.monotonic() - start < .5
        path = AgentSettings.access_path(store.home, w)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"enabled":false}', encoding="utf-8")
        with pytest.raises(AgentError, match="disabled"):
            service.call("job", w, job_id=record["job_id"])
    finally:
        release.set()
        thread.join(5)
