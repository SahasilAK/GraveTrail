"""Shared UI/CLI/MCP image scope, authorization and artifact contracts."""
import asyncio
import base64
import json
from xml.etree import ElementTree as ET

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError, AgentSettings
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def workspace(tmp_path):
    store = Store(tmp_path / 'home')
    w = store.create_workspace('Images / demo')
    Importer(store, w).files([('job.sql', b'create table stage.b as select id from raw.a; '
                             b'create table mart.c as select id from stage.b;')], {'.sql'})
    analyze(store, w)
    service = AgentService(store, AccessPolicy(allow_write=True))
    yield store, w, service
    service.close()
    store.close()


def read(service, w, result):
    data, offset = b'', 0
    while offset < result['bytes']:
        chunk = service.call('artifact_read', w, artifact_id=result['artifact_id'], offset=offset)
        data += base64.b64decode(chunk['data'])
        offset = chunk['next_offset']
    return data


def test_shared_image_and_managed_artifact_have_identical_scope(workspace):
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


def test_mcp_png_and_svg_options(workspace):
    _, w, service = workspace
    server = create_server(service)
    for format in ['svg', 'png']:
        response = asyncio.run(server.call_tool('export_graph', {'workspace_id': w, 'asset': 'mart.c',
            'format': format, 'scale': 2, 'background': 'dark', 'title': 'Review', 'legend': False}))
        assert not response.isError, response
        result = response.structuredContent
        data = read(service, w, result)
        assert result['node_count'] == 3 and result['edge_count'] == 2
        if format == 'svg':
            assert 'Review' in ''.join(ET.fromstring(data).itertext())
        else:
            assert data.startswith(b'\x89PNG')


def test_filters_collapsing_and_stale_revision(workspace):
    from dataforge.services import export_graph_image

    store, w, _ = workspace
    selected = next(a['asset_id'] for a in store.assets(w) if a['name'] == 'mart.c')
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


def test_cli_output_and_invalid_destination_leave_no_new_artifact(workspace, tmp_path):
    store, w, service = workspace
    home = store.home
    service.close()
    store.close()
    runner = CliRunner()
    output = tmp_path / 'lineage.svg'
    args = ['--home', str(home), '--json', '--allow-write', 'export', 'graph', 'mart.c', '-w', w,
            '--format', 'svg', '--output', str(output)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['destination'] == str(output)
    assert ET.fromstring(output.read_bytes()).tag.endswith('svg')
    files = list((home / 'agent/artifacts' / w).iterdir())
    again = runner.invoke(app, args)
    assert again.exit_code != 0
    assert list((home / 'agent/artifacts' / w).iterdir()) == files


def test_explorer_image_download(tmp_path, monkeypatch):
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
    finally:
        get_store.clear()


def test_temporary_contraction_budget_and_failed_render_publish_nothing(workspace, monkeypatch):
    from dataforge.graph import LineageGraph

    store, w, service = workspace
    original = LineageGraph.simplified
    def bounded(self, *args, **kwargs):
        assert kwargs.get('evidence_limit') == 20000
        return original(self, *args, **kwargs)
    monkeypatch.setattr(LineageGraph, 'simplified', bounded)
    result = service.call('artifact_create', w, kind='graph', format='svg', selection={'asset': 'mart.c'})
    assert result['node_count'] == 3
    directory = store.home / 'agent/artifacts' / w
    files = list(directory.iterdir())
    def fail(*args, **kwargs):
        raise ValueError('PNG render time limit exceeded; narrow the graph')
    monkeypatch.setattr('dataforge.graph_image_service.render_graph_image', fail)
    with pytest.raises(AgentError, match='time limit'):
        service.call('artifact_create', w, kind='graph', format='png', selection={'asset': 'mart.c'})
    assert list(directory.iterdir()) == files


def test_temporary_cycle_export_retains_same_nodes_as_ui(workspace):
    from dataforge.graph import LineageGraph
    from dataforge.services import export_graph_image

    store, w, _ = workspace
    citation = store.rows('SELECT statement_id,file_id FROM edges WHERE workspace_id=? LIMIT 1', [w])[0]
    store.execute('DELETE FROM edges WHERE workspace_id=?', [w])
    store.execute('DELETE FROM assets WHERE workspace_id=?', [w])
    for aid, name, temporary in [('s', 'source', False), ('b', 'alpha', True),
                                 ('a', 'beta', True), ('t', 'target', False)]:
        store.execute('INSERT INTO assets VALUES (?,?,?,?,?,?,?)', [aid, w, name, name, 'table', temporary, '{}'])
    for i, (source, target) in enumerate([('s', 'b'), ('b', 'a'), ('a', 'b'), ('a', 't')]):
        store.execute('INSERT INTO edges(edge_id,workspace_id,source_id,target_id,statement_id,file_id,confidence,status) VALUES (?,?,?,?,?,?,?,?)',
                      [str(i), w, source, target, citation['statement_id'], citation['file_id'], 1., 'verified'])
    ui = LineageGraph(store.assets(w), store.edges(w)).simplified(keep=['t']).focus('t', 'upstream', 15, 2000)
    data, _ = export_graph_image(store, w, 't', collapse_temporary=True)
    actual = {n.get('data-node') for n in ET.fromstring(data).findall('.//{http://www.w3.org/2000/svg}g[@data-node]')}
    assert actual == set(ui.nodes)


def test_manifest_write_failure_cleans_binary(workspace, monkeypatch):
    from pathlib import Path

    store, w, service = workspace
    original = Path.open
    def no_manifest(path, *args, **kwargs):
        if path.suffix == '.json' and path.parent.name == w:
            raise OSError('Simulated full disk')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', no_manifest)
    with pytest.raises(AgentError, match='Local file operation failed'):
        service.call('artifact_create', w, kind='graph', format='svg', selection={'asset': 'mart.c'})
    assert not list((store.home / 'agent/artifacts' / w).iterdir())
