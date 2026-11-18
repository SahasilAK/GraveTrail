from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest


def test_sql_example_builds_and_opens_focused_lineage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ui.common import get_store

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=30).run()
    workspace = app.session_state["workspace"]
    next(button for button in app.button if button.label == "Run SQL example").click().run()

    assert not app.exception
    assert app.title[0].value == "Lineage"
    assert app.text_input(key="asset_search_lineage").value == "pub.all_kpis"
    assert any("upstream · depth 30" in caption.value for caption in app.caption)
    assert not app.warning
    store = get_store(str(tmp_path))
    assert len(store.files(workspace)) == 86
    target = next(asset for asset in store.assets(workspace) if asset["name"] == "pub.all_kpis")
    assert app.session_state[f"asset_choice_lineage_{workspace}"] == target["asset_id"]
    assert len(store.edges(workspace)) == 128
    app.switch_page("ui/pages/dashboard.py").run()
    assert all(button.label != "Run SQL example" for button in app.button)
    assert any(header.value == "Explore your workspace lineage" for header in app.subheader)
    assert {"Explore lineage", "Open Lineage Builder", "Import sources", "Open Columns"} <= {
        button.label for button in app.button if button.proto.type == "primary"}
    assert {metric.label: metric.value for metric in app.metric}["Dependencies"] == "128"


def test_workspace_edit_refreshes_sidebar_and_preserves_active_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that workspace edit refreshes sidebar and preserves active identity.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from ui.common import get_store

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    identity = app.session_state["workspace"]
    app.switch_page("ui/pages/settings.py").run()
    app.switch_page("ui/pages/management.py").run()
    app.segmented_control[0].set_value("Storage & transfers").run()
    next(f for f in app.text_input if f.label == "Active workspace name").set_value("Renamed workspace")
    next(f for f in app.text_area if f.label == "Workspace description").set_value("Retained description")
    next(b for b in app.button if b.label == "Save workspace details").click().run()
    assert not app.exception
    assert app.session_state["workspace"] == identity
    assert "Renamed workspace" in app.selectbox(key="workspace").options
    row = get_store(str(tmp_path)).workspaces()[0]
    assert row["description"] == "Retained description"
    next(f for f in app.text_input if f.label == "Active workspace name").set_value("  ")
    next(b for b in app.button if b.label == "Save workspace details").click().run()
    assert app.error and not app.exception
    assert get_store(str(tmp_path)).workspaces()[0]["name"] == "Renamed workspace"


def test_history_archive_and_restore_through_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that history archive and restore through settings.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from dataforge.ingestion import Importer
    from dataforge.services import analyze
    from dataforge.store import Store
    from ui.common import get_store

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    store = Store(tmp_path)
    w = store.create_workspace("History UI")
    for i in range(3):
        Importer(store, w).files([("q.sql", f"CREATE TABLE mart.x AS SELECT id FROM raw.a WHERE id>{i};".encode())], {".sql"})
        analyze(store, w)
    store.close()
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    app.switch_page("ui/pages/settings.py").run()
    app.switch_page("ui/pages/management.py").run()
    app.segmented_control[0].set_value("Storage & transfers").run()
    app.segmented_control[0].set_value("History & staging").run()
    app.session_state["history_maintenance"] = True
    app.run()
    assert not app.exception
    next(n for n in app.number_input if n.label == "Keep recent analysis records").set_value(1)
    next(n for n in app.number_input if n.label == "Keep recent import records").set_value(1)
    app.run()
    next(b for b in app.button if b.label == "Archive eligible history").click().run()
    assert not app.exception
    assert len(get_store(str(tmp_path)).runs(w)) == 1
    next(b for b in app.button if b.label == "Restore selected history").click().run()
    assert not app.exception
    assert len(get_store(str(tmp_path)).runs(w)) == 3


def test_unresolved_queue_preview_request_and_explicit_inferred_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that unresolved queue preview request and explicit inferred merge.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    import json

    import httpx

    from dataforge.assistance_queue import request_review
    from dataforge.ingestion import Importer
    from dataforge.llm import Profile
    from dataforge.services import analyze
    from dataforge.store import Store
    from ui.common import get_store

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    store = Store(tmp_path)
    w = store.create_workspace("Queue UI")
    code = "CREATE TABLE mart.x AS SELECT unknown.id FROM raw.a;"
    Importer(store, w).files([("q.sql", code.encode())], {".sql"})
    analyze(store, w)
    profile = Profile(provider="OmniRoute", base_url="http://localhost:20128/v1", model="synthetic")
    from dataforge.model_capabilities import ModelCapabilities, bind_capabilities
    profile.source_limit_policy = 'token_capacity'
    profile.model_capabilities = bind_capabilities(ModelCapabilities(context_tokens=100000, source='manual'), profile)
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["p", w, "Synthetic", profile.model_dump_json()])
    store.set_setting(w, "default_profile", "p")
    store.close()
    calls = []
    def handler(request: pytest.FixtureRequest) -> Any:
        """Handle handler for the test scenario.

        Args:
            request: Pytest fixture describing the active test request.

        Returns:
            Value produced for the test scenario.
        """
        calls.append(request)
        context = json.loads(json.loads(request.content)["messages"][1]["content"].split("\n", 1)[-1])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"claims": [{
            "source": "raw.a", "target": "mart.x", "operation": "CREATE", "start_line": 1,
            "end_line": 1, "quote": context["source"], "explanation": "Bound read/write", "confidence": .9}]})}}]})
    monkeypatch.setattr("ui.unresolved_review.request_review", lambda *args, **kwargs:
        request_review(*args, **kwargs, transport=httpx.MockTransport(handler)))
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    app.switch_page("ui/pages/analysis.py").run()
    app.segmented_control[0].set_value("Diagnostics").run()
    app.session_state["unresolved_review_panel"] = True
    app.run()
    assert not app.exception and not calls
    assert any(n.label == "Diagnostic to review" for n in app.selectbox)
    assert any(c.value == code for c in app.code)
    # A click from a stale preview cannot send reimported/reanalyzed source unseen.
    changed = code.replace("unknown.id", "unknown.changed")
    active = get_store(str(tmp_path))
    Importer(active, w).files([("q.sql", changed.encode())], {".sql"})
    analyze(active, w)
    next(b for b in app.button if b.label == "Request AI review of this range").click().run()
    assert not app.exception and not calls
    assert any(c.value == changed for c in app.code)
    next(b for b in app.button if b.label == "Request AI review of this range").click().run()
    assert not app.exception and len(calls) == 1, [e.value for e in [*app.error, *app.warning]]
    assert not [e for e in get_store(str(tmp_path)).edges(w) if e["method"] == "llm"]
    assert isinstance(app.session_state["review_result_" + w], str)
    next(b for b in app.button if b.label == "Merge grounded relationships as inferred").click().run()
    assert not app.exception and len(calls) == 1
    assert any(e["method"] == "llm" for e in get_store(str(tmp_path)).edges(w))


@pytest.fixture(autouse=True)
def clear_resources() -> Iterator[None]:
    """Clear cached resources before the test runs."""
    yield
    import streamlit as st
    st.cache_resource.clear()
