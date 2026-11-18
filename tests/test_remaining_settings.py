from pathlib import Path

import pytest


def test_selected_refresh_after_cache_version_or_settings_change_retains_other_facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that selected refresh after cache version or settings change retains other facts.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from dataforge import services
    from dataforge.ingestion import Importer
    from dataforge.store import Store

    store = Store(tmp_path)
    try:
        w = store.create_workspace("Cache transition")
        Importer(store, w).files([("a.sql", b"create table mart.a as select id from raw.a;"),
                                 ("b.sql", b"create table mart.b as select id from raw.b;")], {".sql"})
        monkeypatch.setattr(services, "PARSER_VERSION", "4")
        assert services.analyze(store, w)["edges"] == 2
        selected = next(f["file_id"] for f in store.files(w) if f["relative_path"] == "a.sql")
        monkeypatch.setattr(services, "PARSER_VERSION", "5")
        assert services.analyze(store, w, [selected])["edges"] == 2
        store.set_setting(w, "dialect_by_extension", {".sql": "tsql"})
        assert services.analyze(store, w, [selected])["edges"] == 2
    finally:
        store.close()


def test_settings_ui_persists_and_exports_preferences_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that settings ui persists and exports preferences atomically.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    import json
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from dataforge.configuration import export_workspace_configuration, import_workspace_configuration
    from dataforge.store import Store

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve()).run()
    w = app.session_state["workspace"]
    app.switch_page("ui/pages/settings.py").run()
    next(t for t in app.text_area if t.label == "SQL dialect by extension (JSON)").set_value('{".sas":"tsql"}')
    next(s for s in app.slider if s.label == "Minimum lineage confidence in graph views").set_value(.8)
    next(c for c in app.checkbox if c.label == "Include inferred relationships in graph views").uncheck()
    next(s for s in app.selectbox if s.label == "Visible parsing diagnostics").set_value("errors")
    next(s for s in app.selectbox if s.label == "Analyze button mode").set_value("all")
    next(b for b in app.button if b.label == "Save parsing settings").click().run()
    assert not app.exception and app.success
    store = Store(tmp_path)
    try:
        payload = export_workspace_configuration(store, w)
        settings = json.loads(payload)["settings"]
        assert settings["min_lineage_confidence"] == .8 and settings["include_inferred"] is False
        assert settings["diagnostic_visibility"] == "errors" and settings["reanalysis_mode"] == "all"
        next(t for t in app.text_area if t.label == "SQL dialect by extension (JSON)").set_value('{".exe":"tsql"}')
        next(s for s in app.slider if s.label == "Minimum lineage confidence in graph views").set_value(.2)
        next(b for b in app.button if b.label == "Save parsing settings").click().run()
        assert app.error and store.setting(w, "min_lineage_confidence") == .8
        copied = import_workspace_configuration(store, payload)
        assert store.setting(copied, "dialect_by_extension") == {".sas": "tsql"}
        app.switch_page("ui/pages/connections.py").run()
        app.segmented_control[0].set_value("Privacy").run()
        next(s for s in app.selectbox if s.label == "Application log level").set_value("WARNING")
        next(b for b in app.button if b.label == "Save logging level").click().run()
        assert not app.exception and app.success
        assert store.setting("__application__", "log_level") == "WARNING"
        assert "log_level" not in export_workspace_configuration(store, w)
    finally:
        store.close()
        from dataforge.logging_config import configure_logging
        configure_logging("INFO")
