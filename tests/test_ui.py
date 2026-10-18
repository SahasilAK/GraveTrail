from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


def test_empty_dashboard_and_builder(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    assert not app.exception
    assert app.title[0].value == "Overview"
    assert any("GraveTrail" in header.value for header in app.sidebar.header)
    app.switch_page("ui/pages/builder.py").run()
    assert not app.exception
    assert any("Import" in b.label for b in app.button)


def test_theme_picker_saves_native_palette_without_changing_workspace(tmp_path, monkeypatch):
    from ui.themes import PRESETS, current_preset

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path / "home"))
    config = tmp_path / "config.toml"
    config.write_bytes(Path(".streamlit/config.toml").read_bytes())
    monkeypatch.setattr("ui.themes.CONFIG_PATH", config)
    monkeypatch.setattr("ui.themes._loaded_preset", lambda: None)
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    workspace = app.session_state["workspace"]
    app.switch_page("ui/pages/settings.py").run()
    app.segmented_control[0].set_value("Appearance").run()
    palette = next(c for c in app.selectbox if c.label == "Theme preset")
    assert palette.options == list(PRESETS)
    assert len(palette.options) == 18
    assert not any(c.label == "Theme preset" for c in app.segmented_control)
    assert all(name + " dark" in palette.options for name in ["Ocean", "Forest", "Amethyst", "Graphite"])
    palette.set_value("Aubergine dark").run()
    next(b for b in app.button if b.label == "Apply theme").click().run()
    assert not app.exception and current_preset(config) == "Aubergine dark"
    assert app.session_state["workspace"] == workspace
    assert app.session_state["theme_pending"][0] == "Aubergine dark"
    assert not app.success
    monkeypatch.setattr("ui.themes._loaded_preset", lambda: "Aubergine dark")
    app.run()
    assert any("Aubergine dark theme applied" in s.value for s in app.success)


def test_directory_import_analysis_and_pages(tmp_path, monkeypatch):
    from dataforge.ingestion import Importer
    from dataforge.services import analyze
    from dataforge.store import Store

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    store = Store(tmp_path)
    w = store.create_workspace("UI workflow")
    fixture = Path("tests/fixtures/scenario").resolve()
    Importer(store, w, [fixture]).directory(fixture, {".sql", ".sas", ".csv"})
    analyze(store, w)
    store.close()
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    assert not app.exception
    assert app.metric[0].value == "7"
    for path in ["builder", "explorer", "columns", "tools", "settings"]:
        app.switch_page(f"ui/pages/{path}.py").run()
        assert not app.exception, (path, [e.message for e in app.exception])
    app.switch_page("ui/pages/explorer.py").run()
    app.text_input(key="asset_search_lineage").set_value("orders").run()
    chooser = next(c for c in app.selectbox if c.label == "Choose an exact asset")
    assert chooser.value is None
    assert len(chooser.options) == 3
    chooser.select(chooser.options[0]).run()
    assert not app.exception
    assert app.dataframe


def test_provider_profile_form_and_settings_sections(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    app.switch_page("ui/pages/settings.py").run()
    for route, section in [("management", "Storage & transfers"), ("settings", "Resources"),
                           ("settings", "Appearance"), ("connections", "Privacy"),
                           ("connections", "Providers & routing")]:
        app.switch_page(f"ui/pages/{route}.py").run()
        app.segmented_control[0].set_value(section).run()
        assert not app.exception
    for field in app.text_input:
        if field.label == "Model or deployment identifier":
            field.set_value("local-test-model")
    next(b for b in app.button if b.label == "Save provider profile").click().run()
    assert not app.exception
    assert any(s.label == "Default profile" for s in app.selectbox)


def test_workspace_edit_refreshes_sidebar_and_preserves_active_identity(tmp_path, monkeypatch):
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


def test_schema_expansion_and_declaration_evidence_in_columns_and_dictionary(tmp_path, monkeypatch):
    from dataforge.ingestion import Importer
    from dataforge.services import analyze
    from dataforge.store import Store

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    store = Store(tmp_path)
    w = store.create_workspace("Schema UI")
    Importer(store, w).files([("schema.sql", b"CREATE TABLE raw.a (id INT, name TEXT);"),
        ("query.sql", b"SELECT a.* FROM raw.a a;")], {".sql"})
    analyze(store, w)
    store.close()
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    app.switch_page("ui/pages/columns.py").run()
    app.text_input(key="asset_search_columns").set_value("raw.a").run()
    choice = next(c for c in app.selectbox if c.label == "Choose an exact asset")
    choice.select(choice.options[0]).run()
    assert not app.exception
    assert app.metric[0].value == "2"
    usages = app.dataframe[0].value
    assert set(usages["column_name"]) == {"id", "name"}
    assert set(usages["status"]) == {"inferred"}
    assert all("schema.sql" in s for s in usages["schema_source"])
    app.session_state["column_schema_panel"] = True
    app.run()
    assert not app.exception
    assert "schema.sql" in next(s for s in app.selectbox if s.key and s.key.startswith("schema_source_choice_")).options
    app.switch_page("ui/pages/tools.py").run()
    app.segmented_control[0].set_value("Data dictionary").run()
    next(f for f in app.text_input if f.label == "Filter dictionary").set_value("raw.a").run()
    assert not app.exception
    assert set(app.dataframe[0].value["provenance"]) == {"SQL DDL declaration"}


def test_history_archive_and_restore_through_settings(tmp_path, monkeypatch):
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


def test_visualization_preferences_save_and_apply_without_cross_workspace_leak(tmp_path, monkeypatch):
    from dataforge.ingestion import Importer
    from dataforge.services import analyze
    from dataforge.store import Store
    from ui.common import get_store

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    store = Store(tmp_path)
    first, other = store.create_workspace("Preferences"), store.create_workspace("Other preferences")
    for workspace in (first, other):
        Importer(store, workspace).files([("q.sql", b"-- complete source header\nCREATE TABLE mart.x AS SELECT id FROM raw.a;")], {".sql"})
        analyze(store, workspace)
    store.close()
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    app.switch_page("ui/pages/settings.py").run()
    app.segmented_control[0].set_value("Appearance").run()
    next(n for n in app.selectbox if n.label == "Default graph direction").set_value("downstream")
    next(n for n in app.checkbox if n.label == "Collapse temporary steps by default").uncheck()
    next(n for n in app.selectbox if n.label == "Graph labels").set_value("hidden")
    next(n for n in app.selectbox if n.label == "Node palette").set_value("neutral")
    next(n for n in app.slider if n.label == "Edge width").set_value(4)
    next(n for n in app.selectbox if n.label == "Default source view").set_value("relevant")
    next(n for n in app.checkbox if n.label == "Show source line numbers").uncheck()
    next(n for n in app.button if n.label == "Save visualization settings").click().run()
    assert not app.exception
    saved = get_store(str(tmp_path))
    assert saved.setting(first, "graph_labels") == "hidden"
    assert saved.setting(first, "source_view_mode") == "relevant"
    assert saved.setting(other, "graph_labels") is None
    app.switch_page("ui/pages/explorer.py").run()
    app.text_input(key="asset_search_lineage").set_value("raw.a").run()
    choice = next(c for c in app.selectbox if c.label == "Choose an exact asset")
    choice.select(choice.options[0]).run()
    assert not app.exception
    assert next(n for n in app.segmented_control if n.label == "Graph direction").value == "downstream"
    assert next(n for n in app.toggle if n.label == "Collapse temporary steps").value is False
    assert len(app.code) == 1
    assert app.code and all(not c.proto.show_line_numbers for c in app.code)
    # Full source remains explicitly available even in relevant-first mode.
    app.session_state["lineage_source_complete_" + first] = True
    app.run()
    assert not app.exception
    assert len(app.code) == 2
    app.selectbox(key="workspace").set_value(other).run()
    assert not app.exception
    assert next(c for c in app.selectbox if c.label == "Choose an exact asset").value is None
    app.text_input(key="asset_search_lineage").set_value("mart.x").run()
    choice = next(c for c in app.selectbox if c.label == "Choose an exact asset")
    choice.select(choice.options[0]).run()
    assert next(n for n in app.segmented_control if n.label == "Graph direction").value == "upstream"
    assert next(n for n in app.toggle if n.label == "Collapse temporary steps").value is True
    assert next(s for s in app.selectbox if s.label == "Source file").value in {f["file_id"] for f in saved.files(other)}
    assert len(app.code) == 2 and all(c.proto.show_line_numbers for c in app.code)


def test_unresolved_queue_preview_request_and_explicit_inferred_merge(tmp_path, monkeypatch):
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
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["p", w, "Synthetic", profile.model_dump_json()])
    store.set_setting(w, "default_profile", "p")
    store.close()
    calls = []
    def handler(request):
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
    assert not app.exception and len(calls) == 1
    assert not [e for e in get_store(str(tmp_path)).edges(w) if e["method"] == "llm"]
    assert isinstance(app.session_state["review_result_" + w], str)
    next(b for b in app.button if b.label == "Merge grounded relationships as inferred").click().run()
    assert not app.exception and len(calls) == 1
    assert any(e["method"] == "llm" for e in get_store(str(tmp_path)).edges(w))


@pytest.fixture(autouse=True)
def clear_resources():
    yield
    import streamlit as st
    st.cache_resource.clear()
