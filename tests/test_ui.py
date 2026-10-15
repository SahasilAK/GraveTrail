from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


def test_empty_dashboard_and_builder(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    assert not app.exception
    assert app.title[0].value == "Workspace overview"
    app.switch_page("ui/pages/builder.py").run()
    assert not app.exception
    assert any("Import" in b.label for b in app.button)


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
    chooser = app.selectbox(key="asset_choice_lineage")
    assert chooser.value is None
    assert len(chooser.options) == 3
    chooser.select(chooser.options[0]).run()
    assert not app.exception
    assert app.dataframe


def test_provider_profile_form_and_settings_sections(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    app.switch_page("ui/pages/settings.py").run()
    for section in ["Storage and workspaces", "Performance", "Visualization", "Security and privacy", "LLM providers"]:
        app.segmented_control[0].set_value(section).run()
        assert not app.exception
    for field in app.text_input:
        if field.label == "Model or deployment identifier":
            field.set_value("local-test-model")
    next(b for b in app.button if b.label == "Save provider profile").click().run()
    assert not app.exception
    assert any(s.label == "Default profile" for s in app.selectbox)


@pytest.fixture(autouse=True)
def clear_resources():
    yield
    import streamlit as st
    st.cache_resource.clear()
