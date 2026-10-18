import os
from pathlib import Path

import pytest


def test_storage_choices_are_bounded_explicit_paths_and_selection_is_validated(tmp_path):
    from dataforge.storage_locations import allowed_homes, validate_home

    first, second = tmp_path / "first", tmp_path / "second"
    choices = allowed_homes(first, os.pathsep.join([str(second), str(second)]))
    assert choices == [str(first.resolve()), str(second.resolve())]
    assert validate_home(str(second), choices) == str(second.resolve())
    with pytest.raises(ValueError):
        validate_home(str(tmp_path / "unlisted"), choices)
    with pytest.raises(ValueError):
        allowed_homes(first, "relative/home")
    with pytest.raises(ValueError):
        allowed_homes(first, os.pathsep.join(str(tmp_path / str(i)) for i in range(9)))
    assert not first.exists() and not second.exists()  # preview does not create stores


def test_ui_switches_independent_storage_and_preserves_other_sessions(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from dataforge.ingestion import Importer
    from dataforge.store import Store

    first, second = tmp_path / "first", tmp_path / "second"
    monkeypatch.setenv("DATAFORGE_HOME", str(first))
    monkeypatch.setenv("DATAFORGE_STORAGE_LOCATIONS", str(second))
    app = AppTest.from_file(Path("app.py").resolve()).run()
    other_session = AppTest.from_file(Path("app.py").resolve()).run()
    original_workspace = app.session_state["workspace"]
    store = Store(first)
    try:
        Importer(store, original_workspace).files([("keep.sql", b"select id from raw.a;")], {".sql"})
        app.switch_page("ui/pages/settings.py").run()
        app.switch_page("ui/pages/management.py").run()
        app.segmented_control[0].set_value("Storage & transfers").run()
        next(s for s in app.selectbox if s.label == "Storage location").set_value(str(second.resolve())).run()
        next(b for b in app.button if b.label == "Open storage location").click().run()
        assert not app.exception
        assert app.session_state["dataforge_home"] == str(second.resolve())
        assert app.session_state["workspace"] != original_workspace
        other_session.run()
        assert other_session.session_state["workspace"] == original_workspace
        assert len(store.files(original_workspace)) == 1
        app.switch_page("ui/pages/management.py").run()
        app.segmented_control[0].set_value("Storage & transfers").run()
        next(s for s in app.selectbox if s.label == "Storage location").set_value(str(first.resolve())).run()
        next(b for b in app.button if b.label == "Open storage location").click().run()
        assert not app.exception and app.session_state["workspace"] == original_workspace
        assert len(store.files(original_workspace)) == 1
    finally:
        store.close()


def test_ui_failed_storage_open_retains_current_workspace(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    first, invalid = tmp_path / "first", tmp_path / "file"
    invalid.write_text("preserve", encoding="utf-8")
    monkeypatch.setenv("DATAFORGE_HOME", str(first))
    monkeypatch.setenv("DATAFORGE_STORAGE_LOCATIONS", str(invalid))
    app = AppTest.from_file(Path("app.py").resolve()).run()
    original = app.session_state["workspace"]
    app.switch_page("ui/pages/settings.py").run()
    app.switch_page("ui/pages/management.py").run()
    app.segmented_control[0].set_value("Storage & transfers").run()
    next(s for s in app.selectbox if s.label == "Storage location").set_value(str(invalid.resolve())).run()
    next(b for b in app.button if b.label == "Open storage location").click().run()
    assert not app.exception and app.error
    assert app.session_state["workspace"] == original
    assert invalid.read_text(encoding="utf-8") == "preserve"
