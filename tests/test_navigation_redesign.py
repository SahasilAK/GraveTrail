"""Focused routes must preserve context without performing work on navigation."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from ui.common import get_store


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace("Navigation")
    Importer(store, w).files([("q.sql", b"create table mart.x as select id from raw.a;")], {".sql"})
    analyze(store, w)
    yield store, w
    import streamlit as st
    st.cache_resource.clear()


def app():
    return AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()


def test_sources_does_not_render_analysis_or_load_originals(workspace, monkeypatch):
    store, _ = workspace
    def unexpected_original(*args, **kwargs):
        raise AssertionError("Original source loaded eagerly")
    monkeypatch.setattr(store, "original", unexpected_original)
    view = app().switch_page("ui/pages/builder.py").run()
    assert not view.exception
    assert view.title[0].value == "Sources"
    assert not any("Analyze" in b.label for b in view.button)
    assert not any(s.label == "Source file" for s in view.selectbox)


def test_focused_routes_do_not_analyze_or_change_settings(workspace):
    store, w = workspace
    before = len(store.runs(w))
    view = app()
    for route, heading in [("analysis", "Analysis"), ("settings", "Workspace settings"),
                           ("connections", "Connections & AI"), ("management", "Data management"),
                           ("automation", "Automation & access")]:
        view.switch_page(f"ui/pages/{route}.py").run()
        assert not view.exception
        assert view.title[0].value == heading
    assert len(store.runs(w)) == before
    assert store.setting(w, "external_llm", False) is False


def test_lineage_selection_survives_navigation_and_new_workspace_is_clean(workspace):
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


def test_analysis_selection_survives_sources_and_diagnostics_are_lazy(workspace, monkeypatch):
    store, w = workspace
    view = app().switch_page("ui/pages/analysis.py").run()
    fid = store.files(w)[0]["file_id"]
    next(s for s in view.multiselect if s.label.startswith("Files to analyze")).set_value([fid]).run()
    view.switch_page("ui/pages/builder.py").run()
    view.switch_page("ui/pages/analysis.py").run()
    assert next(s for s in view.multiselect if s.label.startswith("Files to analyze")).value == [fid]
    def unexpected_source(*args, **kwargs):
        raise AssertionError("Hidden diagnostic source loaded")
    monkeypatch.setattr(store, "file", unexpected_source)
    view.segmented_control[0].set_value("Diagnostics").run()
    assert not view.exception
    assert not any(s.label == "Diagnostic to review" for s in view.selectbox)


def test_reimport_discards_stale_source_selection_and_cleanup_preview(workspace):
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


def test_existing_provider_selection_keeps_its_protocol(workspace):
    import json

    from dataforge.llm import Profile

    store, w = workspace
    profile = Profile(provider="OpenAI", model="test-model", base_url="https://api.openai.com/v1")
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["p", w, "OpenAI test", profile.model_dump_json()])
    view = app().switch_page("ui/pages/connections.py").run()
    next(s for s in view.selectbox if s.label == "Provider profile").set_value("p").run()
    assert next(s for s in view.selectbox if s.label == "Provider").value == "OpenAI"
    next(s for s in view.text_input if s.label == "Model or deployment identifier").set_value("replacement-model")
    next(b for b in view.button if b.label == "Save provider profile").click().run()
    config = json.loads(store.rows("SELECT config FROM llm_profiles WHERE profile_id='p'")[0]["config"])
    assert config["provider"] == "OpenAI" and config["model"] == "replacement-model"


def test_pending_diagnostic_never_presents_new_source_as_old_evidence(workspace):
    store, w = workspace
    Importer(store, w).files([("q.sql", b"CREATE TABLE mart.x AS SELECT unknown.id FROM raw.a;")], {".sql"})
    analyze(store, w)
    assert store.diagnostics(w)
    Importer(store, w).files([("q.sql", b"SELECT 'replacement source';")], {".sql"})
    view = app().switch_page("ui/pages/analysis.py").run()
    view.segmented_control[0].set_value("Diagnostics").run()
    view.session_state["diagnostic_source_panel"] = True
    view.run()
    assert not view.exception
    assert not view.code
    assert any("pending" in warning.value.lower() for warning in view.warning)
    assert any(panel.label == "Optional AI assistance" for panel in view.expander)


def test_automation_discovery_stays_lazy(workspace, monkeypatch):
    def unexpected_discovery(*args, **kwargs):
        raise AssertionError("Hidden automation tools discovered eagerly")
    monkeypatch.setattr("ui.agent_settings.create_server", unexpected_discovery)
    view = app().switch_page("ui/pages/automation.py").run()
    assert not view.exception
    assert not any(b.label == "Test local agent access" for b in view.button)
