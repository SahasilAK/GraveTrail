"""Focused routes must preserve context without performing work on navigation."""
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from ui.common import get_store


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Provide the workspace fixture used by the tests.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace("Navigation")
    Importer(store, w).files([("q.sql", b"create table mart.x as select id from raw.a;")], {".sql"})
    analyze(store, w)
    yield store, w
    import streamlit as st
    st.cache_resource.clear()


def app() -> Any:
    """Handle app for the test scenario.

    Returns:
        Value produced for the test scenario.
    """
    return AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()


def test_focused_routes_are_read_only_and_automation_discovery_is_lazy(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that focused routes do not analyze or change settings.

    Args:
        workspace: Workspace used by the test.
    """
    store, w = workspace
    before = len(store.runs(w))

    def unexpected_discovery(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Hidden automation tools discovered eagerly")

    monkeypatch.setattr("ui.agent_settings.create_server", unexpected_discovery)
    view = app()
    for route, heading in [("analysis", "Analysis"), ("settings", "Workspace settings"),
                           ("connections", "Connections & AI"), ("management", "Data management"),
                           ("automation", "Automation & access")]:
        view.switch_page(f"ui/pages/{route}.py").run()
        assert not view.exception
        assert view.title[0].value == heading
    assert not any(b.label == 'Test local agent access' for b in view.button)
    assert len(store.runs(w)) == before
    assert store.setting(w, "external_llm", False) is False


def test_lineage_selection_survives_navigation_and_new_workspace_is_clean(workspace: Any) -> None:
    """Verify that lineage selection survives navigation and new workspace is clean.

    Args:
        workspace: Workspace used by the test.
    """
    store, w = workspace
    view = app().switch_page("ui/pages/explorer.py").run()
    asset = next(a["asset_id"] for a in store.assets(w) if a["name"] == "raw.a")
    next(s for s in view.selectbox if s.label == "Choose an exact asset").set_value(asset).run()
    next(s for s in view.segmented_control if s.label == "Graph direction").set_value("downstream").run()
    view.switch_page("ui/pages/builder.py").run()
    view.switch_page("ui/pages/explorer.py").run()
    assert next(s for s in view.selectbox if s.label == "Choose an exact asset").value == asset
    assert next(s for s in view.segmented_control if s.label == "Graph direction").value == "downstream"
    view.switch_page("ui/pages/columns.py").run()
    assert next(s for s in view.selectbox if s.label == "Choose an exact asset").value == asset
    view.switch_page("ui/pages/explorer.py").run()
    other = store.create_workspace("Other")
    view.run()
    view.selectbox(key="workspace").set_value(other).run()
    assert not view.exception
    assert not any(s.label == "Source file" for s in view.selectbox)
    assert not view.code


def test_reimport_discards_stale_source_selection_and_cleanup_preview(workspace: Any) -> None:
    """Verify that reimport discards stale source selection and cleanup preview.

    Args:
        workspace: Workspace used by the test.
    """
    store, w = workspace
    view = app().switch_page("ui/pages/builder.py").run()
    view.segmented_control[0].set_value("Inventory").run()
    view.session_state["inventory_source_panel"] = True
    view.run()
    assert view.code
    view.session_state["cleanup_preview"] = {"stale": True}
    Importer(store, w).files([("q.sql", b"create table mart.changed as select id from raw.a;")], {".sql"})
    view.run()
    assert not view.exception
    assert not view.code
    assert "cleanup_preview" not in view.session_state


def test_migration_entry_and_offline_create(workspace) -> None:
    from dataforge.migration import service

    store, w = workspace
    at = app().switch_page("ui/pages/analysis.py").run()
    next(button for button in at.button if button.label == "Create migration").click().run()
    assert not at.exception
    assert any(title.value == "Migration" for title in at.title)
    at.switch_page("ui/pages/migration.py").run()
    assert next(widget for widget in at.selectbox if widget.label == "Warehouse").options == ["Databricks"]
    next(field for field in at.text_input if field.label == "Project name").set_value("Warehouse migration")
    next(button for button in at.button if button.label == "Preview migration").click().run()
    assert not at.error, [x.value for x in at.error]
    assert any(heading.value == "Preflight" for heading in at.subheader)
    next(button for button in at.button if button.label == "Create migration").click().run()
    assert not at.exception
    assert not at.error and not at.warning, ([x.value for x in at.error], [x.value for x in at.warning])
    project, = service.projects(store, w)
    assert not store.rows("SELECT * FROM migration_activity WHERE workspace_id=?", [w])
    revision = service.convert(store, w, project["id"], project["revision"])
    at.run()
    next(widget for widget in at.segmented_control if widget.label == "Migration view").set_value("Review").run()
    assert not at.exception
    assert {"Converted code", "Inspect conversion", "Engineer comments"} <= {heading.value for heading in at.subheader}
    next(widget for widget in at.selectbox if widget.label == "Attach comment to").set_value("source").run()
    next(field for field in at.text_input if field.label == "Comment author").set_value("Engineer")
    next(field for field in at.text_area if field.label == "Engineer comment or requested input").set_value("Confirm raw input.")
    next(button for button in at.button if button.label == "Post comment").click().run()
    assert not at.exception and not at.error
    note, = service.review_comments(store, w, project["id"])
    assert note["line"] == 1 and note["revision"] == revision["id"]
