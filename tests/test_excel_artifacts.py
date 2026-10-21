"""End-to-end XLSX adapters, snapshot facts and disclosure checks."""
import asyncio
import base64
import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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


def test_cli_xlsx_creation_and_authorized_download(tmp_path: Path) -> None:
    """Verify that cli xlsx creation and authorized download.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    home = tmp_path / 'home'
    store = Store(home)
    w = store.create_workspace('CLI Excel')
    Importer(store, w).files([('job.sql', b'create table b as select id from a;')], {'.sql'})
    analyze(store, w)
    store.close()
    runner = CliRunner()
    common = ['--home', str(home), '--json', '--allow-write']
    result = runner.invoke(app, [*common, 'export', 'paths', 'b', '-w', w, '--format', 'xlsx', '--include-evidence'])
    assert result.exit_code == 0, result.output
    metadata = json.loads(result.output)
    assert metadata['relationship_count'] == 1 and metadata['exported_evidence_count'] == 1
    destination = tmp_path / 'lineage.xlsx'
    downloaded = runner.invoke(app, [*common, 'export', 'download', metadata['artifact_id'], str(destination), '-w', w])
    assert downloaded.exit_code == 0, downloaded.output
    assert zipfile.is_zipfile(destination)


def test_shared_export_rejects_invalid_scope_and_marks_stale_analysis(workspace: Any) -> None:
    """Verify that shared export rejects invalid scope and marks stale analysis.

    Args:
        workspace: Workspace used by the test.
    """
    from dataforge.services import export_lineage_excel

    store, w, _, _ = workspace
    selected = next(a['asset_id'] for a in store.assets(w) if a['name'] == 'mart.sales')
    with pytest.raises(ValueError, match='upstream|downstream'):
        export_lineage_excel(store, w, selected, direction='combined')
    Importer(store, w).files([('new.sql', b'select id from other;')], {'.sql'})
    data, metadata = export_lineage_excel(store, w, selected)
    assert data.startswith(b'PK') and not metadata['complete']
    assert any('current' in warning or 'pending' in warning for warning in metadata['warnings'])


def test_explorer_prepares_excel_with_reviewable_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that explorer prepares excel with reviewable scope.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from ui.common import get_store

    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = get_store(str(tmp_path))
    w = store.create_workspace('UI Excel')
    Importer(store, w).files([('job.sql', b'create table mart.sales as select id from raw.orders;')], {'.sql'})
    analyze(store, w)
    selected = next(a['asset_id'] for a in store.assets(w) if a['name'] == 'mart.sales')
    try:
        page = AppTest.from_file(Path('app.py').resolve(), default_timeout=20).run()
        page.switch_page('ui/pages/explorer.py').run()
        next(s for s in page.selectbox if s.label == 'Choose an exact asset').set_value(selected).run()
        page.session_state['lineage_path_panel'] = True
        page.run()
        assert not page.exception
        next(b for b in page.button if b.label == 'Prepare Excel workbook').click().run()
        assert not page.exception
        assert any(b.proto.label == 'Download Excel workbook' for b in page.get('download_button'))
        assert any('Steps show data dependencies' in c.value for c in page.caption)
    finally:
        get_store.clear()
