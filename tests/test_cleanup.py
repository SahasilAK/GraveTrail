import json
import time

import pytest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def populated(store, name):
    w = store.create_workspace(name)
    Importer(store, w).files([('a.sql', b'CREATE TABLE b AS SELECT id FROM a;')], {'.sql'})
    analyze(store, w)
    return w


def test_cleanup_preview_dependencies_isolation_and_staleness(tmp_path):
    from dataforge.cleanup import apply_cleanup, cleanup_plan

    store = Store(tmp_path)
    w, other = populated(store, 'one'), populated(store, 'two')
    file = store.files(w)[0]
    preview = cleanup_plan(store, w, 'sources', file_ids=[file['file_id']])
    assert preview['records']['source_files'] == 1 and preview['records']['edges'] == 1
    assert store.edges(w) and store.files(w)
    with pytest.raises(ValueError, match='confirmation'):
        apply_cleanup(store, preview, '')
    store.set_setting(w, 'new_setting', 1)
    with pytest.raises(ValueError, match='changed'):
        apply_cleanup(store, preview, 'one')
    preview = cleanup_plan(store, w, 'sources', file_ids=[file['file_id']])
    apply_cleanup(store, preview, 'one')
    assert not store.files(w) and not store.edges(w) and not store.runs(w)
    assert store.edges(other) and store.original(store.files(other)[0]['file_id'])
    assert cleanup_plan(store, w, 'sources')['records']['source_files'] == 0
    store.close()


def test_lineage_jobs_and_shared_blobs(tmp_path):
    from dataforge.cleanup import apply_cleanup, cleanup_plan

    store = Store(tmp_path)
    w, other = populated(store, 'one'), populated(store, 'two')
    jobs = tmp_path / 'agent' / 'jobs'
    jobs.mkdir(parents=True)
    job = jobs / ('a' * 32 + '.json')
    job.write_text(json.dumps({'workspace_id': w, 'status': 'running', 'updated_at': time.time()}))
    with pytest.raises(ValueError, match='active'):
        apply_cleanup(store, cleanup_plan(store, w, 'lineage'), 'one')
    job.unlink()
    apply_cleanup(store, cleanup_plan(store, w, 'lineage'), 'one')
    assert store.files(w) and not store.assets(w)
    apply_cleanup(store, cleanup_plan(store, w, 'workspace'), 'one')
    assert store.files(other)
    gc = cleanup_plan(store, '', 'orphans')
    assert not gc['files']  # identical source shared by remaining workspace
    unrelated = tmp_path / 'personal.txt'
    unrelated.write_text('retain')
    apply_cleanup(store, cleanup_plan(store, '', 'application'), 'RESET DATAFORGE')
    assert not store.workspaces() and unrelated.read_text() == 'retain'
    store.close()


def test_backup_restore_checksums_and_paths(tmp_path):
    from dataforge.database_maintenance import backup, restore_backup

    store = Store(tmp_path / 'home')
    w = populated(store, 'one')
    path = backup(store)
    restored = tmp_path / 'restored'
    restore_backup(path, restored)
    with pytest.raises(ValueError):
        restore_backup(path, restored)
    other = Store(restored)
    assert other.edges(w) == store.edges(w)
    assert other.original(other.files(w)[0]['file_id']) == store.original(store.files(w)[0]['file_id'])
    other.close()
    store.close()


def test_cli_requires_write_permission_saved_preview_and_name(tmp_path):
    from typer.testing import CliRunner

    from dataforge.cli import app

    store = Store(tmp_path / 'home')
    w = populated(store, 'test')
    store.close()
    runner = CliRunner()
    args = ['--home', str(tmp_path / 'home'), '--json']
    preview = tmp_path / 'preview.json'
    result = runner.invoke(app, [*args, '--output', str(preview), 'cleanup', 'lineage', '--workspace', w])
    assert result.exit_code == 0, result.stdout
    assert json.loads(preview.read_text())['records']['edges'] == 1
    apply = ['cleanup', 'lineage', '--workspace', w, '--no-dry-run', '--preview', str(preview), '--confirm', 'test']
    denied = runner.invoke(app, [*args, *apply])
    assert denied.exit_code == 3, denied.stdout
    result = runner.invoke(app, [*args, '--allow-write', *apply])
    assert result.exit_code == 0, result.stdout
    store = Store(tmp_path / 'home')
    assert store.files(w) and not store.edges(w)
    store.close()


def test_mcp_cleanup_is_read_only_even_with_write_policy(tmp_path):
    import asyncio

    from dataforge.agent.contracts import AccessPolicy
    from dataforge.agent.mcp_server import create_server
    from dataforge.agent.service import AgentService

    store = Store(tmp_path)
    w = populated(store, 'test')
    service = AgentService(store, AccessPolicy(allow_write=True))
    server = create_server(service)

    async def check():
        tools = {t.name: t for t in await server.list_tools()}
        assert tools['preview_cleanup'].annotations.readOnlyHint
        assert not any('apply' in name or 'delete' in name for name in tools)
        result = await server.call_tool('preview_cleanup', {'workspace_id': w, 'category': 'lineage'})
        assert result.structuredContent['records']['edges'] == 1
        assert store.edges(w)
    try:
        asyncio.run(check())
    finally:
        service.close()
        store.close()


def test_cleanup_ui_preview_confirmation_backup_and_rebuild(tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv('DATAFORGE_HOME', str(tmp_path))
    store = Store(tmp_path)
    w = populated(store, 'test')
    store.close()
    app = AppTest.from_file(Path('app.py').resolve(), default_timeout=30).run()
    app.switch_page('ui/pages/settings.py').run()
    app.segmented_control[0].set_value('Data Management & Cleanup').run()
    assert not app.exception
    next(s for s in app.selectbox if s.label == 'Cleanup category').set_value('lineage').run()
    next(b for b in app.button if b.label == 'Preview cleanup').click().run()
    assert next(b for b in app.button if b.label == 'Apply previewed cleanup').disabled
    next(t for t in app.text_input if t.label == 'Type test to confirm').set_value('test').run()
    next(b for b in app.button if b.label == 'Apply previewed cleanup').click().run()
    assert not app.exception
    assert list((tmp_path / 'backups').glob('*.zip'))
    next(b for b in app.button if b.label == 'Rebuild lineage').click().run()
    assert not app.exception
    assert any('Lineage rebuilt' in s.value for s in app.success)
    from ui.common import get_store
    assert get_store(str(tmp_path)).edges(w)


def test_orphans_reject_hardlink_and_restore_rejects_traversal(tmp_path):
    import os
    import zipfile

    from dataforge.cleanup import cleanup_plan
    from dataforge.database_maintenance import restore_backup

    store = Store(tmp_path / 'home')
    external = tmp_path / 'personal'
    external.write_bytes(b'keep')
    linked = store.home / 'blobs' / ('f' * 64)
    os.link(external, linked)
    with pytest.raises(ValueError, match='hard link'):
        cleanup_plan(store, '', 'orphans')
    store.close()
    archive = tmp_path / 'evil.zip'
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('../personal', 'bad')
        zipped.writestr('manifest.json', json.dumps({'format': 'dataforge-backup-v1', 'files': {'../personal': 'bad'}}))
    with pytest.raises(ValueError, match='Unsafe'):
        restore_backup(archive, tmp_path / 'restored')
    assert external.read_bytes() == b'keep' and not (tmp_path / 'restored').exists()


def test_maintenance_blocks_new_provider_requests_and_protects_active_requests(tmp_path):
    from dataforge.cleanup import maintenance_guard
    from dataforge.llm_resources import request_slot

    store = Store(tmp_path)
    w = store.create_workspace('test')
    with maintenance_guard(store):
        with pytest.raises(ValueError, match='maintenance'):
            with request_slot(store.home, w, 1):
                pytest.fail('Provider request started during cleanup')
    with request_slot(store.home, w, 1):
        with pytest.raises(ValueError, match='active'):
            with maintenance_guard(store):
                pytest.fail('Maintenance started during provider request')
    store.close()


def test_scoped_agent_cannot_create_whole_home_backup(tmp_path):
    from dataforge.agent.contracts import AccessPolicy, AgentError
    from dataforge.agent.service import AgentService

    store = Store(tmp_path)
    w = populated(store, 'test')
    populated(store, 'private')
    service = AgentService(store, AccessPolicy(allow_write=True, workspaces=(w,)))
    try:
        preview = service.call('cleanup_preview', w, category='lineage')
        with pytest.raises(AgentError, match='backup'):
            service.call('cleanup_apply', w, preview=preview, confirmation='test', backup_first=True)
        assert store.edges(w) and not list((tmp_path / 'backups').glob('*.zip'))
    finally:
        service.close()
        store.close()


def test_provider_validation_cannot_recreate_deleted_workspace_data(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import httpx

    from dataforge.cleanup import apply_cleanup, cleanup_plan
    from dataforge.llm import Profile, assist

    store = Store(tmp_path)
    w = populated(store, 'test')
    ready, resume = threading.Event(), threading.Event()

    def validate(*args):
        ready.set()
        assert resume.wait(10)
    monkeypatch.setattr('dataforge.llm.validate_response', validate)
    profile = Profile(provider='Ollama', base_url='http://localhost:11434', model='test')
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={'message': {'content': '{}'}}))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(assist, store, w, profile, store.files(w)[0]['file_id'], 1, 1, transport=transport)
        assert ready.wait(10)
        try:
            with pytest.raises(ValueError, match='active'):
                apply_cleanup(store, cleanup_plan(store, w, 'workspace'), 'test')
        finally:
            resume.set()
            future.result(timeout=10)
    assert store.workspaces() and store.files(w)
    store.close()


def test_restore_refuses_manifest_valid_backup_missing_referenced_blob(tmp_path):
    import zipfile

    from dataforge.database_maintenance import backup, inspect_database, restore_backup

    store = Store(tmp_path / 'home')
    w = populated(store, 'test')
    archive = backup(store)
    digest = store.files(w)[0]['content_hash']
    broken = tmp_path / 'missing-blob.zip'
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(broken, 'w') as rewritten:
        manifest = json.loads(original.read('manifest.json'))
        manifest['files'].pop('blobs/' + digest)
        for item in original.infolist():
            if item.filename not in {'manifest.json', 'blobs/' + digest}:
                rewritten.writestr(item, original.read(item))
        rewritten.writestr('manifest.json', json.dumps(manifest))
    with pytest.raises(ValueError, match='integrity'):
        restore_backup(broken, tmp_path / 'restore')
    (store.home / 'blobs' / digest).unlink()
    assert not inspect_database(store)['ok']
    with pytest.raises(ValueError, match='integrity'):
        backup(store)
    assert not (tmp_path / 'restore').exists()
    store.close()
