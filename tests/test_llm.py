import json

import httpx
import pytest
from pydantic import ValidationError

from dataforge.ingestion import Importer
from dataforge.llm import Adapter, GroundedResponse, Profile, assist, validate_response
from dataforge.services import analyze
from dataforge.store import Store


def test_profile_rejects_credentials_and_insecure_remote_url():
    with pytest.raises(ValidationError):
        Profile(provider="OpenAI", base_url="http://remote.example/v1", model="model")
    with pytest.raises(ValidationError):
        Profile(provider="OpenAI", base_url="https://secret@example.com/v1", model="model")


@pytest.mark.parametrize("provider,path", [("OpenAI", "/v1/chat/completions"),
    ("Anthropic", "/v1/messages"), ("Ollama", "/api/chat"),
    ("Gemini", "/v1beta/models/model:generateContent"),
    ("Databricks", "/serving-endpoints/model/invocations"),
    ("Azure OpenAI", "/openai/deployments/model/chat/completions")])
def test_provider_protocol(provider, path):
    def handler(request):
        assert request.url.path == path
        payload = json.loads(request.content)
        assert "temperature" not in payload
        if provider == "Anthropic":
            assert request.headers["anthropic-version"] == "2023-06-01"
            return httpx.Response(200, json={"content": [{"type": "text", "text": '{"claims":[]}'}], "usage": {"input_tokens": 10}})
        if provider == "Ollama":
            assert payload["stream"] is False
            return httpx.Response(200, json={"message": {"content": '{"claims":[]}'}, "prompt_eval_count": 10})
        if provider == "Gemini":
            assert payload["generationConfig"]["responseMimeType"] == "application/json"
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"claims":[]}'}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"claims":[]}'}}], "usage": {"total_tokens": 10}})
    base = "http://localhost:1234" + {"Ollama": "", "Gemini": "/v1beta", "Databricks": ""}.get(provider, "/v1" if provider != "Azure OpenAI" else "")
    profile = Profile(provider=provider, base_url=base, model="model")
    with Adapter(profile, transport=httpx.MockTransport(handler)) as adapter:
        response, usage = adapter.complete("Return JSON", "Analyze this")
    assert json.loads(response) == {"claims": []}


def test_grounding_rejects_hallucinations_and_invalid_lines():
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


def test_privacy_gate_and_malformed_quarantine(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace("A")
    Importer(store, w).files([("q.sql", b"create table mart.x as select id from raw.a;")], {".sql"})
    analyze(store, w)
    fid = store.files(w)[0]["file_id"]
    remote = Profile(provider="OpenAI", base_url="https://api.openai.com/v1", model="manual")
    with pytest.raises(ValueError, match="disabled"):
        assist(store, w, remote, fid, 1, 1)
    local = Profile(provider="Ollama", base_url="http://localhost:11434", model="manual")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"message": {"content": "not JSON"}}))
    result = assist(store, w, local, fid, 1, 1, transport=transport)
    assert result["outcome"] == "quarantined"
    assert store.rows("SELECT outcome FROM llm_records")[0]["outcome"] == "quarantined"
    store.close()


def test_grounded_merge_stays_inferred_and_survives_refresh(tmp_path):
    from dataforge.llm import merge_claims
    store = Store(tmp_path)
    w = store.create_workspace("A")
    code = "create table mart.x as select id from raw.a;"
    Importer(store, w).files([("q.sql", code.encode())], {".sql"})
    analyze(store, w)
    fid = store.files(w)[0]["file_id"]
    payload = {"claims": [{"source": "raw.a", "target": "mart.x", "operation": "CREATE", "start_line": 1,
        "end_line": 1, "quote": code, "explanation": "Explicit source and target", "confidence": .99}]}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"message": {"content": json.dumps(payload)}}))
    result = assist(store, w, Profile(provider="Ollama", base_url="http://localhost:11434", model="manual"), fid, 1, 1, transport=transport)
    assert result["outcome"] == "validated"
    assert merge_claims(store, w, result["record_id"]) == 1
    analyze(store, w)
    inferred = [e for e in store.edges(w) if e["method"] == "llm"]
    assert len(inferred) == 1 and inferred[0]["status"] == "inferred"
    assert inferred[0]["confidence"] <= .8
    Importer(store, w).files([("q.sql", b"select id from raw.a;")], {".sql"})
    analyze(store, w)
    assert not [e for e in store.edges(w) if e["method"] == "llm"]
    store.close()


def test_versioned_prompt_schema_and_templates():
    from dataforge.llm import PROMPTS, TASKS
    assert json.loads((PROMPTS / "schemas/grounded_response.json").read_text()) == GroundedResponse.model_json_schema()
    for task in TASKS:
        system = (PROMPTS / task / "system.md").read_text()
        assert "untrusted" in system and "Counterexample" in system
        assert (PROMPTS / task / "user_template.md").read_text().count("{{context}}") == 1
