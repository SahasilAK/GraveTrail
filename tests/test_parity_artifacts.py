import asyncio
import base64
import hashlib
import io
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
    Importer(store, w).files([('folder/q.sql', original)], {'.sql'})
    analyze(store, w)
    fid = store.files(w)[0]['file_id']
    service = AgentService(store, AccessPolicy(allow_write=True))
    try:
        server = create_server(service)
        result = asyncio.run(server.call_tool('export_original_source', {'workspace_id': w, 'file_id': fid}))
        assert not result.isError, result
        artifact = result.structuredContent
        chunks, offset = [], 0
        while offset < artifact['bytes']:
            part = service.call('artifact_read', w, artifact_id=artifact['artifact_id'], offset=offset, length=7)
            chunks.append(base64.b64decode(part['data']))
            offset = part['next_offset']
        assert b''.join(chunks) == original
        assert hashlib.sha256(b''.join(chunks)).hexdigest() == artifact['sha256']
        with pytest.raises(AgentError):
            service.call('artifact_read', w, artifact_id=artifact['artifact_id'], offset=-1)
        bundle = service.call('artifact_create', w, kind='source-bundle', format='zip', selection={'file_ids': [fid]})
        data = service.call('artifact_read', w, artifact_id=bundle['artifact_id'])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(data['data']))) as archive:
            assert archive.read('folder/q.sql') == original
        paths = service.call('paths', w, asset='mart.x')
        assert paths['items'][0]['boundary'] == 'root'
        evidence = paths['items'][0]['steps'][0]['evidence'][0]
        assert evidence['source_hash'] == hashlib.sha256(original).hexdigest()
        assert evidence['relative_path'] == 'folder/q.sql' and evidence['start_line'] == 1
        tree = service.call('graph_view', w, asset='mart.x', direction='combined', view='tree')
        assert len(tree['items']) == 2
        html = service.call('artifact_create', w, kind='graph', format='html', selection={'asset': 'mart.x'})
        html_bytes = base64.b64decode(service.call('artifact_read', w, artifact_id=html['artifact_id'])['data'])
        assert b'mountGraph' in html_bytes and b'<script src=' not in html_bytes
        other = store.create_workspace('other')
        with pytest.raises(AgentError):
            service.call('artifact_read', other, artifact_id=artifact['artifact_id'])
        AgentSettings(allow_source=False).save(store, w)
        with pytest.raises(AgentError):
            service.call('artifact_read', w, artifact_id=artifact['artifact_id'])
    finally:
        service.close()
        store.close()


def test_cli_original_download_never_overwrites(tmp_path: Path) -> None:
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
