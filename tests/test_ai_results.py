import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from focused_test_profiles import focused_profile

from dataforge.ingestion import Importer
from dataforge.llm import assist, merge_claims
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Any]:
    """Handle project for the test scenario.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    workspace = store.create_workspace("Task contracts")
    code = "create table mart.x as select a.id from raw.a a;"
    Importer(store, workspace).files([("q.sql", code.encode())], {".sql"})
    analyze(store, workspace)
    yield store, workspace, store.files(workspace)[0]["file_id"], code
    store.close()


def request(project: Any, task: Any, body: str) -> Any:
    """Handle request for the test scenario.

    Args:
        project: Project value used by the test case.
        task: Task value used by the test case.
        body: Body value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    store, workspace, fid, _ = project
    profile = focused_profile(provider="Ollama", base_url="http://localhost:11434", model="test", context_chars=32000)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"message": {"content": json.dumps(body)}}))
    return assist(store, workspace, profile, fid, 1, 1, task=task, transport=transport)


def column(code: Any, **changes: Any) -> dict[Any, Any]:
    """Handle column for the test scenario.

    Args:
        code: Code value used by the test case.
        changes: Changes value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    return {"source": "raw.a", "column": "id", "context": "SELECT", "start_line": 1,
            "end_line": 1, "quote": code, "explanation": "Direct projection", "confidence": .9, **changes}


@pytest.mark.parametrize("changes", [{"column": "phantom"}, {"source": "mart.x"},
    {"context": "WHERE"}, {"quote": "select made_up"}, {"end_line": 10}])
def test_column_contract_quarantines_unsupported_attribution(project: Any, changes: dict[str, Any]) -> None:
    """Verify that column contract quarantines unsupported attribution.

    Args:
        project: Project value used by the test case.
        changes: Changes value used by the test case.
    """
    assert request(project, "column_usage", {"columns": [column(project[3], **changes)]})["outcome"] == "quarantined"


@pytest.mark.parametrize("task", ["column_usage", "code_explanation"])
def test_advisory_tasks_cannot_return_or_merge_lineage_even_legacy(project: Any, task: str) -> None:
    """Verify that advisory tasks cannot return or merge lineage even legacy.

    Args:
        project: Project value used by the test case.
        task: Task value used by the test case.
    """
    store, workspace, _, code = project
    body = {"claims": [{"source": "raw.a", "target": "mart.x", "operation": "CREATE", "quote": code,
                       "start_line": 1, "end_line": 1, "confidence": .9, "explanation": "Legacy"}]}
    result = request(project, task, body)
    assert result["outcome"] == "quarantined"
    # A historical v1 record may contain a valid lineage-shaped result under an advisory task.
    store.execute("UPDATE llm_records SET outcome='validated',details=? WHERE record_id=?",
                  [json.dumps({"content_hash": store.file(project[2])["content_hash"], "result": body}), result["record_id"]])
    with pytest.raises(ValueError, match="lineage"):
        merge_claims(store, workspace, result["record_id"])
    store.execute("UPDATE llm_records SET outcome='merged' WHERE record_id=?", [result["record_id"]])
    analyze(store, workspace)
    assert not [edge for edge in store.edges(workspace) if edge["method"] == "llm"]


@pytest.mark.parametrize("code,quote", [
    ("select id from raw.a join raw.b on raw.a.id=raw.b.id;", "select id from raw.a"),
    ("select 'select id from raw.a;' as example;", "select id from raw.a;")])
def test_citation_cannot_strip_context_or_promote_a_string_to_code(code: str, quote: str) -> None:
    """Verify that citation cannot strip context or promote comment string to code.

    Args:
        code: Code value used by the test case.
        quote: Quote value used by the test case.
    """
    from dataforge.ai_results import ColumnResponse, validate_advisory

    response = ColumnResponse.model_validate({"columns": [column(quote)]})
    source = {"raw_content": code, "extension": ".sql"}
    with pytest.raises(ValueError):
        validate_advisory(response, source, {"raw.a", "raw.b"}, 1, len(code.splitlines()), {})
