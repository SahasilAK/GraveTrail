import asyncio

import pytest

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.services import analyze
from dataforge.store import Store


def test_maintenance_reads_never_archive_or_cleanup(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('maintenance')
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
    finally:
        service.close()
        store.close()


def test_local_history_archive_requires_fresh_preview_confirmation_and_backup(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('local maintenance')
    for _ in range(3):
        analyze(store, w)
    service = AgentService(store, AccessPolicy(allow_write=True))
    try:
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


def test_shared_general_cleanup_refuses_backup_opt_out(tmp_path):
    from dataforge.cleanup import apply_cleanup, cleanup_plan
    store = Store(tmp_path)
    w = store.create_workspace('backed up')
    try:
        preview = cleanup_plan(store, w, 'lineage')
        with pytest.raises(ValueError, match='backup'):
            apply_cleanup(store, preview, 'backed up', backup_first=False)
    finally:
        store.close()
