import asyncio
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError, AgentSettings
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_original_binary_artifact_roundtrip_authorization_and_paths(tmp_path: Path) -> None:
    """Verify that original binary artifact roundtrip authorization and paths.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    w = store.create_workspace('artifacts')
    original = b'\xef\xbb\xbfcreate table mart.x as select id from raw.a;\r\n'
    branch = (b'create temporary table stage.b as select id from raw.b;'
              b'create table mart.b as select id from stage.b;')
    Importer(store, w).files([('folder/q.sql', original), ('branch.sql', branch)], {'.sql'})
    analyze(store, w)
    fid = next(f['file_id'] for f in store.files(w) if f['relative_path'] == 'folder/q.sql')
    service = AgentService(store, AccessPolicy(allow_write=True))
    try:
        server = create_server(service)
        result = asyncio.run(server.call_tool('export_original_source', {'workspace_id': w, 'file_id': fid}))
        assert not result.isError, result
        artifact = result.structuredContent
        def read_artifact(metadata, length=16384):
            chunks, offset = [], 0
            while offset < metadata['bytes']:
                part = service.call('artifact_read', w, artifact_id=metadata['artifact_id'],
                                    offset=offset, length=length)
                assert part['next_offset'] > offset
                chunks.append(base64.b64decode(part['data']))
                offset = part['next_offset']
            data = b''.join(chunks)
            assert hashlib.sha256(data).hexdigest() == metadata['sha256']
            return data

        assert read_artifact(artifact, length=7) == original
        with pytest.raises(AgentError):
            service.call('artifact_read', w, artifact_id=artifact['artifact_id'], offset=-1)
        bundle = service.call('artifact_create', w, kind='source-bundle', format='zip', selection={'file_ids': [fid]})
        with zipfile.ZipFile(io.BytesIO(read_artifact(bundle))) as archive:
            assert archive.read('folder/q.sql') == original
        paths = service.call('paths', w, asset='mart.x')
        assert paths['items'][0]['boundary'] == 'root'
        evidence = paths['items'][0]['steps'][0]['evidence'][0]
        assert evidence['source_hash'] == hashlib.sha256(original).hexdigest()
        assert evidence['relative_path'] == 'folder/q.sql' and evidence['start_line'] == 1
        tree = service.call('graph_view', w, asset='mart.x', direction='combined', view='tree')
        assert len(tree['items']) == 2
        html = service.call('artifact_create', w, kind='graph', format='html', selection={'asset': 'mart.x'})
        html_bytes = read_artifact(html)
        assert b'mountGraph(document.body,' in html_bytes and b'<script src=' not in html_bytes

        options = {'collapse_temporary': True}
        query = {'workspace_id': w, 'all_assets': True, 'options': options}
        graph = asyncio.run(server.call_tool('get_graph_data', query))
        assert not graph.isError, graph
        assert {r['name'] for r in graph.structuredContent['items']} == {'raw.a', 'raw.b', 'mart.x', 'mart.b'}
        steps = service.call('steps', w, all_assets=True, options=options)
        assert {(r['source'], r['target']) for r in steps['items']} == {('raw.a', 'mart.x'), ('raw.b', 'mart.b')}
        columns = asyncio.run(server.call_tool('get_graph_data', {**query, 'view': 'columns'}))
        assert not columns.isError and any(r['name'] == 'mart.b' and r['column'] == 'id' for r in columns.structuredContent['items'])
        links = asyncio.run(server.call_tool('get_graph_data', {**query, 'view': 'column-links'}))
        assert not links.isError and any(r['source_name'] == 'raw.b' and r['target_name'] == 'mart.b'
                                        and r['source'] == r['target'] == 'id' and r['value']
                                        for r in links.structuredContent['items'])
        export = asyncio.run(server.call_tool('export_graph', {**query, 'format': 'json'}))
        assert not export.isError, export
        assert len(json.loads(read_artifact(export.structuredContent))['nodes']) == 4

        Importer(store, w).files([('folder/q.sql', b'create table mart.x as select new_id from raw.a;')], {'.sql'})
        selection = {'file_id': fid, 'content_hash': evidence['source_hash'], 'start_line': 1, 'end_line': 1}
        historical = asyncio.run(server.call_tool('get_source_evidence', {'workspace_id': w, **selection}))
        assert not historical.isError and not historical.structuredContent['source_current']
        assert historical.structuredContent['items'][0]['code'] == original.decode('utf-8-sig')
        other = store.create_workspace('other')
        with pytest.raises(AgentError):
            service.call('artifact_read', other, artifact_id=artifact['artifact_id'])
        with pytest.raises(AgentError, match='workspace'):
            service.call('source', other, **selection)
        AgentSettings(allow_source=False).save(store, w)
        with pytest.raises(AgentError):
            service.call('artifact_read', w, artifact_id=artifact['artifact_id'])
        with pytest.raises(AgentError, match='Source'):
            service.call('source', w, **selection)
    finally:
        service.close()
        store.close()
    result = CliRunner().invoke(app, ['--home', str(tmp_path), '--json', '--collapse-temporary', 'lineage', 'graph',
                                      '--all-assets', '--view', 'column-links', '-w', w])
    assert result.exit_code == 0 and len(json.loads(result.output)['items']) == 2, result.output


def test_cli_original_download_never_overwrites_or_leaves_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that cli original download never overwrites.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path / 'home')
    w = store.create_workspace('download')
    original = b'select id from raw.a;\r\n'
    Importer(store, w).files([('a.sql', original)], {'.sql'})
    fid = store.files(w)[0]['file_id']
    store.close()
    destination = tmp_path / 'download.sql'
    args = ['--home', str(tmp_path / 'home'), '--json', '--allow-write', 'source', 'download', fid,
            str(destination), '-w', w]
    first = CliRunner().invoke(app, args)
    assert first.exit_code == 0, first.output
    assert destination.read_bytes() == original
    second = CliRunner().invoke(app, args)
    assert second.exit_code != 0 and destination.read_bytes() == original
    read = AgentService._artifact_read

    def interrupted(self, workspace, options, artifact_id, offset=0):
        if offset:
            raise AgentError("conflict", "Download interrupted")
        return read(self, workspace, options, artifact_id, length=4)

    monkeypatch.setattr(AgentService, "_artifact_read", interrupted)
    retry_path = tmp_path / "retry.sql"
    args[args.index(str(destination))] = str(retry_path)
    interrupted_result = CliRunner().invoke(app, args)
    assert interrupted_result.exit_code != 0 and "Download interrupted" in interrupted_result.output
    assert not retry_path.exists()


def test_cycle_paths_are_explicitly_incomplete(tmp_path: Path) -> None:
    """Verify that cycle paths are explicitly incomplete.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    w = store.create_workspace('cycle')
    Importer(store, w).files([('a.sql', b'create table a as select id from b; create table b as select id from a;')], {'.sql'})
    analyze(store, w)
    service = AgentService(store)
    try:
        result = service.call('paths', w, asset='a')
        assert any(p['boundary'] == 'cycle' for p in result['items'])
        assert not result['complete'] and result['boundaries']
    finally:
        service.close()
        store.close()
