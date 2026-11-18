from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


def test_explorer_reports_missing_assets_without_crashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that explorer reports missing assets without crashing.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from dataforge.graph import LineageGraph
    from ui import common

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve()).run()
    graph = LineageGraph(
        [{"asset_id": "mart", "name": "mart.output", "kind": "table", "temporary": False}],
        [{"edge_id": "broken", "source_id": "missing", "target_id": "mart"}])
    monkeypatch.setattr(common, "_cached_graph", lambda *args: graph)
    app.switch_page("ui/pages/explorer.py").run()
    assert not app.exception
    assert any("relationships reference missing assets" in item.value for item in app.warning)
    selector = next(s for s in app.selectbox if s.label == "Choose an exact asset")
    assert selector.options == ["mart.output  [table]", "All"]
    selector.set_value("mart").run()
    assert not app.exception
