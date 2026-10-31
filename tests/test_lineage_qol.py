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


def sources(app: Any) -> Any:
    """Handle sources for the test scenario.

    Args:
        app: App value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    return next(s for s in app.selectbox if s.label == "Source file").options


def test_graph_sources_follow_direction_and_combined_deduplicates(lineage: Any) -> None:
    """Verify that graph sources follow direction and combined deduplicates.

    Args:
        lineage: Lineage value used by the test case.
    """
    app, store, w, assets = lineage
    store.set_setting(w, "graph_limit", 150)
    choose(app, assets["mart.middle"])
    assert sources(app) == ["up.sql"]
    next(s for s in app.segmented_control if s.label == "Graph direction").set_value("downstream").run()
    assert sources(app) == ["down.sql"]
    next(s for s in app.segmented_control if s.label == "Graph direction").set_value("combined").run()
    assert set(sources(app)) == {"up.sql", "down.sql"}
    assert len(sources(app)) == len(set(sources(app)))


def test_all_includes_disconnected_graph_beyond_focus_limit(lineage: Any) -> None:
    """Verify that all includes disconnected graph beyond focus limit.

    Args:
        lineage: Lineage value used by the test case.
    """
    app, _, _, _ = lineage
    chooser = next(s for s in app.selectbox if s.label == "Choose an exact asset")
    assert "All" in chooser.options
    chooser.select("All").run()
    assert not app.exception
    assert any("5 assets" in c.value for c in app.caption)
    assert set(sources(app)) == {"up.sql", "down.sql", "island.sql"}
    assert next(s for s in app.slider if s.label == "Traversal depth").disabled


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


def test_shared_graph_focus_survives_first_500_limit(lineage: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that shared graph focus survives first 500 limit.

    Args:
        lineage: Lineage value used by the test case.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from dataforge.graph import LineageGraph
    from ui import common

    app, store, w, _ = lineage
    graph = LineageGraph([{"asset_id": f"a{i}", "name": f"table_{i:03}", "kind": "table",
                           "temporary": False, "metadata": "{}"} for i in range(501)], [])
    # Graph selection must identify a real workspace asset for coverage queries.
    with store.transaction():
        store.db.executemany('INSERT INTO assets VALUES (?,?,?,?,?,?,?)',
            [(f'a{i}', w, f'table_{i:03}', f'table_{i:03}', 'table', False, '{}') for i in range(501)])
    monkeypatch.setattr(common, "_cached_graph", lambda *args: graph)
    app.text_input(key="asset_search_lineage").set_value("table_500").run()
    choose(app, "a500")
    app.switch_page("ui/pages/columns.py").run()
    assert not app.exception
    assert next(s for s in app.selectbox if s.label == "Choose an exact asset").value == "a500"
    assert app.session_state["exploration_asset_" + w] == "a500"


def test_history_restores_tree_tab_and_controls() -> None:
    """Verify that history restores tree tab and controls."""
    from ui.lineage_navigation import move_history, remember_view

    state = {}
    first = {"asset": "a", "query": "first", "direction": "combined", "depth": 7,
             "simplified": False, "view": "Tree", "tree_direction": "Upstream dependencies"}
    second = {**first, "asset": "b", "query": "second", "tree_direction": "Downstream dependencies"}
    remember_view(state, "w", first)
    remember_view(state, "w", second)
    state["lineage_direction_tabs"] = "Downstream dependencies"
    move_history(state, "w", -1)
    assert state["lineage_direction_tabs"] == "Upstream dependencies"
    assert state["asset_search_lineage"] == "first"
    assert state["graph_direction_w"] == "combined"
    assert state["graph_depth_w"] == 7
    assert state["graph_collapse_w"] is False
    assert state["lineage_view_w"] == "Tree"
