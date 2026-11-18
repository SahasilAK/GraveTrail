import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from dataforge.ingestion import Importer
from dataforge.llm import Profile, merge_claims
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def queued(tmp_path: Path) -> Iterator[Any]:
    """Handle queued for the test scenario.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    workspace = store.create_workspace("Diagnostic review")
    code = "CREATE TABLE mart.x AS SELECT unknown.id FROM raw.a;"
    Importer(store, workspace).files([("q.sql", (code + "\nCREATE TABLE mart.y AS SELECT id FROM raw.b;").encode())], {".sql"})
    analyze(store, workspace)
    profile = Profile(provider="OmniRoute", base_url="http://localhost:20128/v1", model="synthetic")
    from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
    profile.source_limit_policy = 'token_capacity'
    profile.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=100000, source='manual'), profile)
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["test-profile", workspace, "Synthetic", profile.model_dump_json()])
    store.set_setting(workspace, "default_profile", "test-profile")
    yield store, workspace, code
    store.close()


def test_review_request_routes_grounded_result_then_requires_explicit_merge(queued: Any) -> None:
    """Verify that review request routes grounded result then requires explicit merge.

    Args:
        queued: Queued value used by the test case.
    """
    from dataforge.assistance_queue import diagnostic_context, diagnostic_queue, request_review

    store, workspace, code = queued
    item = diagnostic_queue(store, workspace)["items"][0]
    preview = diagnostic_context(store, workspace, item["diagnostic_id"])
    requests = []
    def respond(request: pytest.FixtureRequest) -> Any:
        """Handle respond for the test scenario.

        Args:
            request: Pytest fixture describing the active test request.

        Returns:
            Value produced for the test scenario.
        """
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
