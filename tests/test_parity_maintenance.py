import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.services import analyze
from dataforge.store import Store


def test_mcp_previews_history_and_local_archive_requires_confirmation_and_backup(tmp_path: Path) -> None:
    store = Store(tmp_path)
    w = store.create_workspace('local maintenance')
    for _ in range(3):
        analyze(store, w)
    store.set_setting(w, 'auto_cleanup_temporary', True)
    service = AgentService(store, AccessPolicy(allow_write=True))
    try:
        assert service.call('settings_get', w, section='temporary_cleanup')['values']['enabled']
        server = create_server(service)
        result = asyncio.run(server.call_tool('preview_history_archive', {'workspace_id': w, 'keep_runs': 1}))
        assert not result.isError and len(result.structuredContent['analysis_runs']) == 2
        assert len(store.runs(w)) == 3
        names = {tool.name for tool in asyncio.run(server.list_tools())}
        assert not {'archive_history', 'restore_history', 'cleanup_temporary', 'checkpoint', 'backup'} & names
        with pytest.raises(AgentError):
            service.call('database_inspect')
        plan = service.call('history_preview', w, keep_runs=1)
        with pytest.raises(AgentError):
            service.call('history_archive', w, preview=plan, confirmation='wrong')
        result = service.call('history_archive', w, preview=plan, confirmation='local maintenance')
        assert result['analysis_runs'] == 2 and result['backup_id']
        restored = service.call('history_restore', w, archive_id=result['archive_id'], confirmation='local maintenance')
        assert restored['analysis_runs'] == 2
    finally:
        service.close()
        store.close()


def test_shared_general_cleanup_refuses_backup_opt_out(tmp_path: Path) -> None:
    """Require a local admin, an unredacted preview, and a backup for shared cleanup."""
    from dataforge.cleanup import apply_cleanup, cleanup_plan
    store = Store(tmp_path)
    workspace = store.create_workspace('backed up')
    service = AgentService(store, AccessPolicy(allow_application_config=True))
    try:
        preview = cleanup_plan(store, workspace, 'lineage')
        with pytest.raises(ValueError, match='backup'):
            apply_cleanup(store, preview, 'backed up', backup_first=False)
        result = asyncio.run(create_server(service).call_tool('preview_cleanup', {
            'workspace_id': workspace, 'category': 'cache',
        }))
        assert not result.isError and 'token' not in result.structuredContent and 'files' not in result.structuredContent
    finally:
        service.close()
        store.close()

    runner = CliRunner()
    args = ['--home', str(tmp_path), '--json', '--allow-write', '--allow-config-write', '--allow-application-config']
    command = ['cleanup', 'cache']
    denied = runner.invoke(app, [*args, *command])
    assert json.loads(denied.stdout)['error']['code'] == 'requires_local_admin'

    args.append('--allow-admin')
    preview = runner.invoke(app, [*args, *command])
    assert preview.exit_code == 0, preview.output
    plan = json.loads(preview.stdout)
    assert plan['workspace_id'] == '' and plan['token']
    preview_path = tmp_path / 'cache-preview.json'
    preview_path.write_text(preview.stdout, encoding='utf-8')
    apply = ['--no-dry-run', '--preview', str(preview_path), '--confirm', 'CLEAN SHARED DATA']
    denied = runner.invoke(app, [*args, *command, *apply, '--no-backup'])
    assert json.loads(denied.stdout)['error']['code'] == 'validation_failed'
    cleaned = runner.invoke(app, [*args, *command, *apply])
    assert cleaned.exit_code == 0, cleaned.output
    assert Path(json.loads(cleaned.stdout)['backup']).is_file()
