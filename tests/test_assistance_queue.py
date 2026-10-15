import json

import httpx
import pytest

from dataforge.ingestion import Importer
from dataforge.llm import Profile, merge_claims
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def queued(tmp_path):
    store = Store(tmp_path)
    workspace = store.create_workspace("Diagnostic review")
    code = "CREATE TABLE mart.x AS SELECT unknown.id FROM raw.a;"
    Importer(store, workspace).files([("q.sql", (code + "\nCREATE TABLE mart.y AS SELECT id FROM raw.b;").encode())], {".sql"})
    analyze(store, workspace)
    profile = Profile(provider="OmniRoute", base_url="http://localhost:20128/v1", model="synthetic")
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["test-profile", workspace, "Synthetic", profile.model_dump_json()])
    store.set_setting(workspace, "default_profile", "test-profile")
    yield store, workspace, code
    store.close()


def test_review_queue_is_bounded_and_previews_only_relevant_statement(queued):
    from dataforge.assistance_queue import diagnostic_context, diagnostic_queue

    store, workspace, code = queued
    items = diagnostic_queue(store, workspace)
    assert len(items["items"]) == 1 and not items["truncated"]
    item = items["items"][0]
    preview = diagnostic_context(store, workspace, item["diagnostic_id"])
    assert preview["code"] == code
    assert preview["task"] == "sql_lineage"
    assert preview["first"] == preview["last"] == 1
    other = store.create_workspace("Other")
    assert diagnostic_queue(store, other)["items"] == []
    with pytest.raises(ValueError):
        diagnostic_context(store, other, item["diagnostic_id"])
    for i in range(105):
        store.execute("INSERT INTO diagnostics VALUES (?,?,?,?,?,?,?)",
                      [str(i), workspace, item["file_id"], 2, "warning", "Unsupported statement", ""])
    bounded = diagnostic_queue(store, workspace)
    assert len(bounded["items"]) == 100 and bounded["truncated"]
    # Reimported source has pending analysis; old diagnostics are not offered for new code.
    Importer(store, workspace).files([("q.sql", b"SELECT id FROM raw.changed;")], {".sql"})
    assert diagnostic_queue(store, workspace)["items"] == []


def test_review_request_routes_grounded_result_then_requires_explicit_merge(queued):
    from dataforge.assistance_queue import diagnostic_context, diagnostic_queue, request_review

    store, workspace, code = queued
    item = diagnostic_queue(store, workspace)["items"][0]
    preview = diagnostic_context(store, workspace, item["diagnostic_id"])
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        context = json.loads(body["messages"][1]["content"].split("\n", 1)[-1])
        assert context["source"] == code and context["start_line"] == context["end_line"] == 1
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"claims": [{
            "source": "raw.a", "target": "mart.x", "operation": "CREATE", "start_line": 1,
            "end_line": 1, "quote": code, "explanation": "Explicit source and target", "confidence": .9}]})}}]})
    result = request_review(store, workspace, item["diagnostic_id"], preview["content_hash"], 1, 1,
                            transport=httpx.MockTransport(respond))
    assert len(requests) == 1 and result["outcome"] == "validated"
    assert not [e for e in store.edges(workspace) if e["method"] == "llm"]
    assert merge_claims(store, workspace, result["record_id"]) == 1
    analyze(store, workspace)
    assert any(e["method"] == "llm" and e["status"] == "inferred" for e in store.edges(workspace))
    assert diagnostic_queue(store, workspace)["items"]  # A claim does not resolve a column warning.


def test_review_rejects_changed_preview_and_preserves_privacy_before_network(queued):
    from dataforge.assistance_queue import diagnostic_context, diagnostic_queue, request_review

    store, workspace, _ = queued
    item = diagnostic_queue(store, workspace)["items"][0]
    preview = diagnostic_context(store, workspace, item["diagnostic_id"])
    def forbidden(request):
        raise AssertionError("No request should be sent")
    transport = httpx.MockTransport(forbidden)
    remote = Profile(provider="OpenAI", base_url="https://api.openai.com/v1", model="synthetic")
    store.execute("UPDATE llm_profiles SET config=?", [remote.model_dump_json()])
    with pytest.raises(ValueError, match="disabled"):
        request_review(store, workspace, item["diagnostic_id"], preview["content_hash"], 1, 1, transport=transport)
    Importer(store, workspace).files([("q.sql", b"SELECT id FROM raw.new;")], {".sql"})
    with pytest.raises(ValueError, match="changed|analy|current"):
        request_review(store, workspace, item["diagnostic_id"], preview["content_hash"], 1, 1, transport=transport)


def test_review_quarantines_invalid_output_without_changing_facts(queued):
    from dataforge.assistance_queue import diagnostic_context, diagnostic_queue, request_review

    store, workspace, _ = queued
    item = diagnostic_queue(store, workspace)["items"][0]
    preview = diagnostic_context(store, workspace, item["diagnostic_id"])
    before = store.edges(workspace)
    result = request_review(store, workspace, item["diagnostic_id"], preview["content_hash"], 1, 1,
        transport=httpx.MockTransport(lambda request: httpx.Response(200,
            json={"choices": [{"message": {"content": "invented prose"}}]})))
    assert result["outcome"] == "quarantined" and store.edges(workspace) == before


def test_review_pins_preview_even_if_import_changes_after_queue_lookup(queued, monkeypatch):
    from dataforge.assistance_queue import diagnostic_context, diagnostic_queue, request_review

    store, workspace, _ = queued
    item = diagnostic_queue(store, workspace)["items"][0]
    preview = diagnostic_context(store, workspace, item["diagnostic_id"])
    read = store.file
    def import_before_read(file_id):
        Importer(store, workspace).files([("q.sql", b"SELECT id FROM raw.changed;")], {".sql"})
        return read(file_id)
    monkeypatch.setattr(store, "file", import_before_read)
    def forbidden(request):
        raise AssertionError("Changed source must not be transmitted")
    with pytest.raises(ValueError, match="changed"):
        request_review(store, workspace, item["diagnostic_id"], preview["content_hash"], 1, 1,
                        transport=httpx.MockTransport(forbidden))


def test_review_queue_sas_fallback_ignores_info_and_csv(queued):
    from dataforge.assistance_queue import diagnostic_context, diagnostic_queue

    store, workspace, _ = queued
    Importer(store, workspace).files([("unresolved.sas", b"data work.x;\nset &missing;\nrun;"),
                                      ("data.csv", b"id\n1\n")], {".sas", ".csv"})
    analyze(store, workspace)
    csv_id = next(f["file_id"] for f in store.files(workspace) if f["extension"] == ".csv")
    store.execute("INSERT INTO diagnostics VALUES (?,?,?,?,?,?,?)", ["csv", workspace, csv_id, 1, "error", "CSV error", ""])
    sql_id = next(f["file_id"] for f in store.files(workspace) if f["extension"] == ".sql")
    store.execute("INSERT INTO diagnostics VALUES (?,?,?,?,?,?,?)", ["info", workspace, sql_id, 1, "info", "Informational only", ""])
    items = diagnostic_queue(store, workspace)["items"]
    assert all(i["extension"] != ".csv" and i["severity"] != "info" for i in items)
    sas = next(i for i in items if i["extension"] == ".sas")
    preview = diagnostic_context(store, workspace, sas["diagnostic_id"])
    assert preview["task"] == "sas_lineage" and preview["bounded_context"]
    assert "&missing" in preview["code"] and preview["last"] <= 40
