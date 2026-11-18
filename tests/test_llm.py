import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from focused_test_profiles import focused_profile
from pydantic import ValidationError

from dataforge.ingestion import Importer
from dataforge.llm import Adapter, GroundedResponse, Profile, assist, validate_response
from dataforge.services import analyze
from dataforge.store import Store


def test_profile_rejects_credentials_and_insecure_remote_url() -> None:
    """Verify that profile rejects credentials and insecure remote url."""
    with pytest.raises(ValidationError):
        Profile(provider="OpenAI", base_url="http://remote.example/v1", model="model")
    with pytest.raises(ValidationError):
        Profile(provider="OpenAI", base_url="https://secret@example.com/v1", model="model")


@pytest.mark.parametrize("provider,path", [("OpenAI", "/v1/chat/completions"),
    ("Anthropic", "/v1/messages"), ("Ollama", "/api/chat"),
    ("Gemini", "/v1beta/models/model:generateContent"),
    ("Databricks", "/serving-endpoints/model/invocations"),
    ("Azure OpenAI", "/openai/deployments/model/chat/completions")])
def test_provider_protocol(provider: str, path: str) -> None:
    """Verify that provider protocol.

    Args:
        provider: Provider value used by the test case.
        path: Path value used by the test case.
    """
    finish = {'Anthropic': 'max_tokens', 'Gemini': 'MAX_TOKENS'}.get(provider, 'length')

    def handler(request: pytest.FixtureRequest) -> Any:
        """Handle handler for the test scenario.

        Args:
            request: Pytest fixture describing the active test request.

        Returns:
            Value produced for the test scenario.
        """
        assert request.url.path == path
        payload = json.loads(request.content)
        assert "temperature" not in payload
        if provider == "Anthropic":
            assert request.headers["anthropic-version"] == "2023-06-01"
            return httpx.Response(200, json={"content": [{"type": "text", "text": '{"claims":[]}'}],
                                             "stop_reason": finish})
        if provider == "Ollama":
            assert payload["stream"] is False
            return httpx.Response(200, json={"message": {"content": '{"claims":[]}'}, "done_reason": finish})
        if provider == "Gemini":
            assert payload["generationConfig"]["responseMimeType"] == "application/json"
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"claims":[]}'}]},
                                                           "finishReason": finish}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"claims":[]}'},
                                                       "finish_reason": finish}]})
    base = "http://localhost:1234" + {"Ollama": "", "Gemini": "/v1beta", "Databricks": ""}.get(provider, "/v1" if provider != "Azure OpenAI" else "")
    profile = Profile(provider=provider, base_url=base, model="model")
    with Adapter(profile, transport=httpx.MockTransport(handler)) as adapter:
        response, _ = adapter.complete("Return JSON", "Analyze this")
        assert adapter.completion_metadata['finish_reason'] == finish
        assert adapter.completion_metadata['truncated']
        assert not adapter.completion_metadata['usage_known']
    assert json.loads(response) == {"claims": []}


def test_grounding_rejects_hallucinations_and_invalid_lines() -> None:
    """Verify that grounding rejects hallucinations and invalid lines."""
    code = "create table mart.x as select id from raw.a;"
    response = GroundedResponse.model_validate({"claims": [{"source": "raw.a", "target": "mart.x", "operation": "CREATE", "start_line": 1, "end_line": 1, "quote": code, "explanation": "Explicit source and target", "confidence": .8}]})
    assert validate_response(response, code, {"raw.a", "mart.x"}, 1, 1)
    response.claims[0].source = "secret.phantom"
    with pytest.raises(ValueError, match="known|evidence"):
        validate_response(response, code, {"raw.a", "mart.x"}, 1, 1)
    response.claims[0].source = "raw.a"
    response.claims[0].end_line = 99
    with pytest.raises(ValueError, match="range"):
        validate_response(response, code, {"raw.a", "mart.x"}, 1, 1)


def test_privacy_gate_and_malformed_quarantine(tmp_path: Path) -> None:
    """Verify that privacy gate and malformed quarantine.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    w = store.create_workspace("A")
    Importer(store, w).files([("q.sql", b"create table mart.x as select id from raw.a;")], {".sql"})
    analyze(store, w)
    fid = store.files(w)[0]["file_id"]
    remote = Profile(provider="OpenAI", base_url="https://api.openai.com/v1", model="manual")
    with pytest.raises(ValueError, match="disabled"):
        assist(store, w, remote, fid, 1, 1)
    local = focused_profile(provider="Ollama", base_url="http://localhost:11434", model="manual")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"message": {"content": "not JSON"}}))
    result = assist(store, w, local, fid, 1, 1, transport=transport)
    assert result["outcome"] == "quarantined"
    assert store.rows("SELECT outcome FROM llm_records")[0]["outcome"] == "quarantined"
    store.close()


def test_grounded_merge_stays_inferred_and_survives_refresh(tmp_path: Path) -> None:
    """Verify that grounded merge stays inferred and survives refresh.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.llm import merge_claims
    from dataforge.services import set_source_dialect
    store = Store(tmp_path)
    w = store.create_workspace("A")
    code = "create table mart.x as select id from raw.a;"
    Importer(store, w).files([("q.sql", code.encode())], {".sql"})
    analyze(store, w)
    fid = store.files(w)[0]["file_id"]
    payload = {"claims": [{"source": "raw.a", "target": "mart.x", "operation": "CREATE", "start_line": 1,
        "end_line": 1, "quote": code, "explanation": "Explicit source and target", "confidence": .99}]}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"message": {"content": json.dumps(payload)}}))
    result = assist(store, w, focused_profile(provider="Ollama", base_url="http://localhost:11434", model="manual"), fid, 1, 1, transport=transport)
    assert result["outcome"] == "validated"
    assert merge_claims(store, w, result["record_id"]) == 1
    analyze(store, w)
    inferred = [e for e in store.edges(w) if e["method"] == "llm"]
    assert len(inferred) == 1 and inferred[0]["status"] == "inferred"
    assert inferred[0]["confidence"] <= .8
    store.execute("UPDATE llm_records SET created_at=current_timestamp - INTERVAL '31 days' WHERE record_id=?", [result["record_id"]])
    review = assist(store, w, focused_profile(provider="Ollama", base_url="http://localhost:11434", model="manual"), fid, 1, 1, transport=transport)
    analyze(store, w)
    assert len([e for e in store.edges(w) if e["method"] == "llm"]) == 1
    set_source_dialect(store, w, fid, 'databricks')
    with pytest.raises(ValueError, match='dialect changed'):
        merge_claims(store, w, review['record_id'])
    analyze(store, w)
    assert not [e for e in store.edges(w) if e['method'] == 'llm']
    set_source_dialect(store, w, fid, None)
    analyze(store, w)
    assert len([e for e in store.edges(w) if e['method'] == 'llm']) == 1
    Importer(store, w).files([("q.sql", b"select id from raw.a;")], {".sql"})
    analyze(store, w)
    assert not [e for e in store.edges(w) if e["method"] == "llm"]
    store.close()
