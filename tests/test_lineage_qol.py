"""Navigation and direction regressions against real imported lineage."""
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from ui.common import get_store


@pytest.fixture
def lineage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Handle lineage for the test scenario.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace("QOL")
    Importer(store, w).files([
        ("up.sql", b"create table mart.middle as select id from raw.a;"),
        ("down.sql", b"create table mart.final as select id from mart.middle;"),
        ("island.sql", b"create table mart.island as select id from raw.island;")], {".sql"})
    analyze(store, w)
    store.set_setting(w, "graph_limit", 2)
    assets = {a["name"]: a["asset_id"] for a in store.assets(w)}
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    app.switch_page("ui/pages/explorer.py").run()
    yield app, store, w, assets
    import streamlit as st
    st.cache_resource.clear()


def choose(app: Any, asset: Any) -> None:
    """Handle choose for the test scenario.

    Args:
        app: App value used by the test case.
        asset: Asset used by the test.
    """
    next(s for s in app.selectbox if s.label == "Choose an exact asset").set_value(asset).run()
    assert not app.exception


def test_back_forward_restore_search_controls_and_new_branch(lineage: Any) -> None:
    """Verify that back forward restore search controls and new branch.

    Args:
        lineage: Lineage value used by the test case.
    """
    app, _, w, assets = lineage
    app.text_input(key="asset_search_lineage").set_value("middle").run()
    choose(app, assets["mart.middle"])
    app.text_input(key="asset_search_lineage").set_value("").run()
    choose(app, assets["mart.final"])
    next(b for b in app.button if b.label == "Back").click().run()
    assert not app.exception
    assert next(s for s in app.selectbox if s.label == "Choose an exact asset").value == assets["mart.middle"]
    next(b for b in app.button if b.label == "Forward").click().run()
    assert next(s for s in app.selectbox if s.label == "Choose an exact asset").value == assets["mart.final"]
    next(b for b in app.button if b.label == "Back").click().run()
    choose(app, assets["raw.a"])
    assert next(b for b in app.button if b.label == "Forward").disabled
    # History contains IDs and controls only, scoped to this workspace.
    assert app.session_state["lineage_history_" + w]["entries"]


def test_graph_focus_updates_exact_choice_outside_search_and_shared_context(lineage: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that graph focus updates exact choice outside search and shared context.

    Args:
        lineage: Lineage value used by the test case.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    import streamlit as st

    from ui import common
    from ui.lineage_navigation import focus_asset

    app, _, w, assets = lineage
    app.text_input(key="asset_search_lineage").set_value("middle").run()
    choose(app, assets["mart.middle"])
    original = common.graph_view

    def graph_with_focus(*args: Any, **kwargs: Any) -> Any:
        """Handle graph with focus for the test scenario.

        Args:
            args: Positional arguments forwarded to the operation.
            kwargs: Keyword arguments forwarded to the operation.

        Returns:
            Value produced for the test scenario.
        """
        st.button("Focus raw.a", on_click=focus_asset, args=(st.session_state, w, assets["raw.a"], "raw.a"))
        return original(*args, **kwargs)

    monkeypatch.setattr(common, "graph_view", graph_with_focus)
    app.run()
    next(b for b in app.button if b.label == "Focus raw.a").click().run()
    assert not app.exception
    assert app.text_input(key="asset_search_lineage").value == "raw.a"
    assert next(s for s in app.selectbox if s.label == "Choose an exact asset").value == assets["raw.a"]
    app.switch_page("ui/pages/columns.py").run()
    assert next(s for s in app.selectbox if s.label == "Choose an exact asset").value == assets["raw.a"]
