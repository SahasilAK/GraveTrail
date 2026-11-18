"""End-to-end XLSX adapters, snapshot facts and disclosure checks."""
import asyncio
import base64
import hashlib
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dataforge.agent.contracts import AccessPolicy, AgentError, AgentSettings
from dataforge.agent.mcp_server import create_server
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
    w = store.create_workspace('Excel demo')
    raw = b'create table staging.clean as select id from raw.orders; create table mart.sales as select id from staging.clean;'
    Importer(store, w).files([('job.sql', raw)], {'.sql'})
    analyze(store, w)
    service = AgentService(store, AccessPolicy(allow_write=True))
    yield store, w, service, raw
    service.close()
    store.close()


def artifact_bytes(service: Any, w: Any, artifact: Any) -> Any:
    """Handle artifact bytes for the test scenario.

    Args:
        service: Service value used by the test case.
        w: Workspace identifier used by the test.
        artifact: Artifact value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    chunks, offset = [], 0
    while offset < artifact['bytes']:
        result = service.call('artifact_read', w, artifact_id=artifact['artifact_id'], offset=offset)
        chunks.append(base64.b64decode(result['data']))
        offset = result['next_offset']
    return b''.join(chunks)


def test_xlsx_artifact_metadata_default_disclosure_and_revocation(workspace: Any) -> None:
    """Verify that xlsx artifact metadata default disclosure and revocation.

    Args:
        workspace: Workspace used by the test.
    """
    store, w, service, raw = workspace
    args = {'kind': 'paths', 'format': 'xlsx', 'selection': {'asset': 'mart.sales'}}
    result = service.call('artifact_create', w, **args)
    assert result['filename'].endswith('.xlsx')
    assert result['mime_type'] == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert result['relationship_count'] == 2 and result['path_count'] == 1
    assert result['revision'] == store.runs(w)[0]['run_id']
    data = artifact_bytes(service, w, result)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = b' '.join(archive.read(n) for n in archive.namelist() if n.endswith('.xml'))
        assert raw not in xml and b'create table' not in xml
        assert b'name="Evidence"' not in archive.read('xl/workbook.xml')
    # XLSX retains lineage authorization even with citations excluded.
    AgentSettings(allow_source=False).save(store, w)
    with pytest.raises(AgentError, match='Source retrieval'):
        service.call('artifact_read', w, artifact_id=result['artifact_id'])
    with pytest.raises(AgentError, match='Source retrieval'):
        service.call('artifact_create', w, **args)


def test_mcp_evidence_hash_and_explicit_raw_source_option(workspace: Any) -> None:
    """Verify that mcp evidence hash and explicit raw source option.

    Args:
        workspace: Workspace used by the test.
    """
    _, w, service, raw = workspace
    server = create_server(service)
    result = asyncio.run(server.call_tool('export_dependency_paths', {'workspace_id': w,
        'asset': 'mart.sales', 'format': 'xlsx', 'include_evidence': True}))
    assert not result.isError, result
    artifact = result.structuredContent
    assert artifact['exported_evidence_count'] == 2
    with zipfile.ZipFile(io.BytesIO(artifact_bytes(service, w, artifact))) as archive:
        xml = b' '.join(archive.read(n) for n in archive.namelist() if n.endswith('.xml'))
        assert hashlib.sha256(raw).hexdigest().encode() in xml and b'create table' not in xml
        assert b'name="Evidence"' in archive.read('xl/workbook.xml')
    with pytest.raises(AgentError):
        service.call('artifact_create', w, kind='paths', format='xlsx',
                     selection={'asset': 'mart.sales', 'include_source_text': True})
    explicit = service.call('artifact_create', w, kind='paths', format='xlsx',
        selection={'asset': 'mart.sales', 'include_evidence': True, 'include_source_text': True})
    with zipfile.ZipFile(io.BytesIO(artifact_bytes(service, w, explicit))) as archive:
        assert b'create table' in archive.read('xl/worksheets/sheet3.xml')
