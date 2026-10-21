import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from dataforge.ingestion import Importer
from dataforge.llm import Profile, assist, merge_claims
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
    profile = Profile(provider="Ollama", base_url="http://localhost:11434", model="test", context_chars=32000)
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


def test_column_contract_persists_without_creating_lineage(project: Any) -> None:
    """Verify that column contract persists without creating lineage.

    Args:
        project: Project value used by the test case.
    """
    store, workspace, _, code = project
    before = store.edges(workspace)
    result = request(project, "column_usage", {"columns": [column(code)], "unresolved_symbols": []})
    assert result["outcome"] == "validated"
    assert result["result"]["columns"][0]["column"] == "id"
    saved = store.rows("SELECT details,prompt_hash FROM llm_records WHERE record_id=?", [result["record_id"]])[0]
    assert json.loads(saved["details"])["schema_version"] == "2"
    assert store.rows("SELECT version FROM prompt_versions WHERE prompt_hash=?", [saved["prompt_hash"]])[0]["version"] == "2"
    with pytest.raises(ValueError, match="lineage"):
        merge_claims(store, workspace, result["record_id"])
    assert store.edges(workspace) == before


@pytest.mark.parametrize("changes", [{"column": "phantom"}, {"source": "mart.x"},
    {"context": "WHERE"}, {"quote": "select made_up"}, {"end_line": 10}])
def test_column_contract_quarantines_unsupported_attribution(project: Any, changes: dict[str, Any]) -> None:
    """Verify that column contract quarantines unsupported attribution.

    Args:
        project: Project value used by the test case.
        changes: Changes value used by the test case.
    """
    assert request(project, "column_usage", {"columns": [column(project[3], **changes)]})["outcome"] == "quarantined"


def test_explanation_requires_exact_citations_and_known_assets(project: Any) -> None:
    """Verify that explanation requires exact citations and known assets.

    Args:
        project: Project value used by the test case.
    """
    _, _, _, code = project
    item = {"text": "The statement projects id from raw.a.", "assets": ["raw.a", "mart.x"],
            "start_line": 1, "end_line": 1, "quote": code}
    result = request(project, "code_explanation", {"explanations": [item]})
    assert result["outcome"] == "validated"
    with pytest.raises(ValueError, match="lineage"):
        merge_claims(project[0], project[1], result["record_id"])
    item["assets"] = ["raw.phantom"]
    assert request(project, "code_explanation", {"explanations": [item]})["outcome"] == "quarantined"
    item["assets"] = ["raw.a"]
    item["quote"] = "not source"
    assert request(project, "code_explanation", {"explanations": [item]})["outcome"] == "quarantined"


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


def test_cannot_attribute_derived_column_to_base_table(project: Any) -> None:
    """Verify that cannot attribute derived column to base table.

    Args:
        project: Project value used by the test case.
    """
    store, workspace, fid, _ = project
    code = "with c as (select id from raw.a) select c.id from c;"
    Importer(store, workspace).files([("q.sql", code.encode())], {".sql"})
    analyze(store, workspace)
    body = {"columns": [column("select c.id from c;", context="SELECT")]}
    assert request((store, workspace, fid, code), "column_usage", body)["outcome"] == "quarantined"


@pytest.mark.parametrize("task,field", [("column_usage", "columns"), ("code_explanation", "explanations")])
def test_advisory_ui_reopens_stored_results_with_citations_and_no_merge(project: Any, task: str, field: str) -> None:
    """Verify that advisory ui reopens stored results with citations and no merge.

    Args:
        project: Project value used by the test case.
        task: Task value used by the test case.
        field: Field value used by the test case.
    """
    from streamlit.testing.v1 import AppTest

    store, workspace, _, code = project
    item = column(code) if task == "column_usage" else {
        "text": "Projects id", "assets": ["raw.a"], "quote": code, "start_line": 1, "end_line": 1}
    result = request(project, task, {field: [item]})
    assert result["outcome"] == "validated"

    def page(home: "Any", workspace: "Any", record: "Any") -> None:
        """Handle page for the test scenario.

        Args:
            home: Home value used by the test case.
            workspace: Workspace used by the test.
            record: Record value used by the test case.
        """
        import streamlit as st

        from dataforge.store import Store
        from ui.assistance_result import render_result

        db = Store(home)
        st.session_state["saved"] = record
        render_result(db, workspace, "saved")
        db.close()

    app = AppTest.from_function(page, args=(store.home, workspace, result["record_id"])).run()
    assert not app.exception
    assert app.code[0].value == code
    assert not any("Merge" in button.label for button in app.button)
    if task == "column_usage":
        assert app.dataframe[0].value.iloc[0]["status"] == "AI-inferred"
    Importer(store, workspace).files([("q.sql", b"select changed from raw.a;")], {".sql"})
    app.run()
    assert not app.exception
    assert any("Source changed" in warning.value for warning in app.warning)


def test_task_schema_files_match_contracts() -> None:
    """Verify that task schema files match contracts."""
    from dataforge.ai_results import ColumnResponse, ExplanationResponse
    from dataforge.llm import PROMPTS

    for name, model in [("column_response", ColumnResponse), ("explanation_response", ExplanationResponse)]:
        assert json.loads((PROMPTS / "schemas" / (name + ".json")).read_text()) == model.model_json_schema()


@pytest.mark.parametrize("code,quote", [
    ("select id from raw.a join raw.b on raw.a.id=raw.b.id;", "select id from raw.a"),
    ("-- select id from raw.a;\nselect 1;", "select id from raw.a;"),
    ("select 'select id from raw.a;' as example;", "select id from raw.a;")])
def test_citation_cannot_strip_context_or_promote_comment_string_to_code(project: Any, code: str, quote: str) -> None:
    """Verify that citation cannot strip context or promote comment string to code.

    Args:
        project: Project value used by the test case.
        code: Code value used by the test case.
        quote: Quote value used by the test case.
    """
    from dataforge.ai_results import ColumnResponse, validate_advisory

    response = ColumnResponse.model_validate({"columns": [column(quote)]})
    source = {"raw_content": code, "extension": ".sql"}
    with pytest.raises(ValueError):
        validate_advisory(response, source, {"raw.a", "raw.b"}, 1, len(code.splitlines()), {})


def test_saved_results_remain_available_without_provider_profile(project: Any) -> None:
    """Verify that saved results remain available without provider profile.

    Args:
        project: Project value used by the test case.
    """
    from streamlit.testing.v1 import AppTest

    store, workspace, _, code = project
    request(project, "column_usage", {"columns": [column(code)]})

    def page(home: "Any", workspace: "Any") -> None:
        """Handle page for the test scenario.

        Args:
            home: Home value used by the test case.
            workspace: Workspace used by the test.
        """
        from dataforge.store import Store
        from ui.assistance import render

        db = Store(home)
        render(db, workspace)
        db.close()

    app = AppTest.from_function(page, args=(store.home, workspace)).run()
    assert not app.exception
    assert next(s for s in app.selectbox if s.label == "Saved AI result").options


@pytest.mark.parametrize("code", ["data work.x; set raw.a; keep id; run;",
    "data work.x;\n  set raw.a;\n  keep id;\nrun;"])
def test_sas_citations_preserve_original_block_formatting(code: str) -> None:
    """Verify that sas citations preserve original block formatting.

    Args:
        code: Code value used by the test case.
    """
    from dataforge.ai_results import ColumnResponse, validate_advisory

    result = ColumnResponse.model_validate({"columns": [column(code, context="KEEP", end_line=len(code.splitlines()))]})
    source = {"raw_content": code, "extension": ".sas"}
    assert validate_advisory(result, source, {"raw.a"}, 1, len(code.splitlines()), {})
