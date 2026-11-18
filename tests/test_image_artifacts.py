"""Shared UI/CLI/MCP image scope, authorization and artifact contracts."""
import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dataforge.agent.contracts import AccessPolicy, AgentError, AgentSettings
from dataforge.agent.service import AgentService
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Any]:
    """Provide the workspace fixture used by the tests.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path / 'home')
    w = store.create_workspace('Images / demo')
    Importer(store, w).files([('job.sql', b'create table stage.b as select id from raw.a; '
                             b'create table mart.c as select id from stage.b;')], {'.sql'})
    analyze(store, w)
    service = AgentService(store, AccessPolicy(allow_write=True))
    yield store, w, service
    service.close()
    store.close()


def read(service: Any, w: Any, result: Any) -> Any:
    """Handle read for the test scenario.

    Args:
        service: Service value used by the test case.
        w: Workspace identifier used by the test.
        result: Result produced by the operation.

    Returns:
        Value produced for the test scenario.
    """
    data, offset = b'', 0
    while offset < result['bytes']:
        chunk = service.call('artifact_read', w, artifact_id=result['artifact_id'], offset=offset)
        data += base64.b64decode(chunk['data'])
        offset = chunk['next_offset']
    return data


def test_shared_image_and_managed_artifact_have_identical_scope(workspace: Any) -> None:
    """Verify that shared image and managed artifact have identical scope.

    Args:
        workspace: Workspace used by the test.
    """
    from dataforge.services import export_graph_image

    store, w, service = workspace
    selected = next(a['asset_id'] for a in store.assets(w) if a['name'] == 'mart.c')
    ui, summary = export_graph_image(store, w, selected, max_depth=1)
    result = service.call('artifact_create', w, options={'max_depth': 1}, kind='graph', format='svg',
                          selection={'asset': 'mart.c'})
    assert read(service, w, result) == ui
    assert result['node_count'] == summary['node_count'] == 2
    assert result['edge_count'] == 1 and not result['complete']
    assert result['revision'] == store.runs(w)[0]['run_id']
    assert result['graph_revision'] and 'Depth' in str(result['warnings'])
    assert result['mime_type'] == 'image/svg+xml'
    assert result['filename'].startswith('gravetrail-') and '/' not in result['filename']
    assert b'create table' not in ui
    AgentSettings(allow_source=False).save(store, w)
    with pytest.raises(AgentError, match='Source retrieval'):
        read(service, w, result)


def test_image_filters_and_stale_export_revisions(workspace: Any) -> None:
    """Verify that filters collapsing and stale revision.

    Args:
        workspace: Workspace used by the test.
    """
    from dataforge.services import export_graph_image, export_lineage_excel

    store, w, _ = workspace
    selected = next(a['asset_id'] for a in store.assets(w) if a['name'] == 'mart.c')
    with pytest.raises(ValueError, match='upstream|downstream'):
        export_lineage_excel(store, w, selected, direction='combined')
    store.execute("UPDATE assets SET temporary=true WHERE name='stage.b' AND workspace_id=?", [w])
    _, a = export_graph_image(store, w, selected, collapse_temporary=True)
    _, b = export_graph_image(store, w, selected, collapse_temporary=False)
    assert a['node_count'] == 2 and b['node_count'] == 3
    assert 'collapsed' in str(a['warnings'])
    store.set_setting(w, 'min_lineage_confidence', 1.0)
    store.execute('UPDATE edges SET confidence=0.5 WHERE workspace_id=?', [w])
    svg, filtered = export_graph_image(store, w, selected)
    assert filtered['node_count'] == 1 and b'minimum confidence 1' in svg
    assert filtered['graph_revision'] != a['graph_revision']
    Importer(store, w).files([('new.sql', b'select id from other;')], {'.sql'})
    _, stale = export_graph_image(store, w, selected)
    assert not stale['complete'] and 'not current' in str(stale['warnings'])
    data, workbook = export_lineage_excel(store, w, selected)
    assert data.startswith(b'PK') and not workbook['complete']
    assert any('current' in warning or 'pending' in warning for warning in workbook['warnings'])


def test_explorer_prepares_image_and_excel_downloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that explorer image download.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from ui.common import get_store

    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('Image UI')
    Importer(store, w).files([('job.sql', b'create table b as select id from a;')], {'.sql'})
    analyze(store, w)
    try:
        page = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
        page.switch_page('ui/pages/explorer.py').run()
        selected = next(a['asset_id'] for a in store.assets(w) if a['name'] == 'b')
        next(s for s in page.selectbox if s.label == 'Choose an exact asset').set_value(selected).run()
        assert not page.exception
        next(b for b in page.button if b.label == 'Prepare graph image').click().run()
        assert not page.exception
        assert any(b.proto.label == 'Download SVG' for b in page.get('download_button'))
        assert any('independent of browser pan/zoom' in c.value for c in page.caption)

        page.session_state['lineage_path_panel'] = True
        page.run()
        next(b for b in page.button if b.label == 'Prepare Excel workbook').click().run()
        assert not page.exception
        assert any(b.proto.label == 'Download Excel workbook' for b in page.get('download_button'))
        assert any('Steps show data dependencies' in c.value for c in page.caption)
    finally:
        get_store.clear()


def test_temporary_contraction_budget_and_failed_render_publish_nothing(workspace: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that temporary contraction budget and failed render publish nothing.

    Args:
        workspace: Workspace used by the test.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        ValueError: Raised by the test helper.
    """
    from dataforge.graph import LineageGraph

    store, w, service = workspace
    original = LineageGraph.simplified
    def bounded(self, *args: Any, **kwargs: Any) -> Any:
        """Handle bounded for the test scenario.

        Args:
            args: Positional arguments forwarded to the operation.
            kwargs: Keyword arguments forwarded to the operation.

        Returns:
            Value produced for the test scenario.
        """
        assert kwargs.get('evidence_limit') == 20000
        return original(self, *args, **kwargs)
    monkeypatch.setattr(LineageGraph, 'simplified', bounded)
    result = service.call('artifact_create', w, kind='graph', format='svg', selection={'asset': 'mart.c'})
    assert result['node_count'] == 3
    directory = store.home / 'agent/artifacts' / w
    files = list(directory.iterdir())
    def fail(*args: Any, **kwargs: Any) -> None:
        """Raise the injected failure used by the test.

        Args:
            args: Positional arguments forwarded to the operation.
            kwargs: Keyword arguments forwarded to the operation.

        Raises:
            ValueError: Raised by the test helper.
        """
        raise ValueError('PNG render time limit exceeded; narrow the graph')
    monkeypatch.setattr('dataforge.graph_image_service.render_graph_image', fail)
    with pytest.raises(AgentError, match='time limit'):
        service.call('artifact_create', w, kind='graph', format='png', selection={'asset': 'mart.c'})
    assert list(directory.iterdir()) == files


def test_manifest_write_failure_cleans_binary(workspace: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that manifest write failure cleans binary.

    Args:
        workspace: Workspace used by the test.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        OSError: Raised by the test helper.
    """
    from pathlib import Path

    store, w, service = workspace
    original = Path.open
    def no_manifest(path: Any, *args: Any, **kwargs: Any) -> Any:
        """Handle no manifest for the test scenario.

        Args:
            path: Path value used by the test case.
            args: Positional arguments forwarded to the operation.
            kwargs: Keyword arguments forwarded to the operation.

        Returns:
            Value produced for the test scenario.

        Raises:
            OSError: Raised by the test helper.
        """
        if path.suffix == '.json' and path.parent.name == w:
            raise OSError('Simulated full disk')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', no_manifest)
    with pytest.raises(AgentError, match='Local file operation failed'):
        service.call('artifact_create', w, kind='graph', format='svg', selection={'asset': 'mart.c'})
    assert not list((store.home / 'agent/artifacts' / w).iterdir())
