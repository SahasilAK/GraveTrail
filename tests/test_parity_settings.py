import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.store import Store


def test_typed_sections_atomic_conflicts_and_mcp(tmp_path: Path) -> None:
    """Verify that typed sections atomic conflicts and mcp.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    w = store.create_workspace('settings')
    service = AgentService(store, AccessPolicy(allow_write=True, allow_config_write=True))
    try:
        schemas = service.call('settings_schema', w)
        assert set(schemas['sections']) == {'parsing', 'analysis', 'resources', 'visualization', 'privacy', 'agent_access', 'temporary_cleanup'}
        before = service.call('settings_get', w, section='resources')
        with pytest.raises(AgentError):
            service.call('settings_update', w, section='resources', values={'parse_workers': 9, 'max_files': 5}, expected_revision=before['settings_revision'])
        assert service.call('settings_get', w, section='resources') == before
        result = service.call('settings_update', w, section='resources', values={'parse_workers': 3}, expected_revision=before['settings_revision'])
        assert result['changed_fields'] == ['parse_workers']
        with pytest.raises(AgentError, match='changed'):
            service.call('settings_update', w, section='resources', values={'parse_workers': 2}, expected_revision=before['settings_revision'])
        server = create_server(service)
        actual = asyncio.run(server.call_tool('get_workspace_settings', {'workspace_id': w, 'section': 'resources'}))
        assert actual.structuredContent['values']['parse_workers'] == 3
        assert not actual.isError
    finally:
        service.close()
        store.close()
    result = CliRunner().invoke(app, ['--home', str(tmp_path), '--json', 'settings', 'get', 'resources', '-w', w])
    assert result.exit_code == 0 and json.loads(result.output)['values']['parse_workers'] == 3


@pytest.mark.parametrize('section,patch', [('privacy', {'external_llm': True}), ('privacy', {'redact_secrets': False}), ('privacy', {'max_context_chars': 10000}), ('agent_access', {'max_chars': 20000}), ('temporary_cleanup', {'enabled': True})])
def test_settings_refuse_escalation(tmp_path: Path, section: str, patch: dict[str, Any]) -> None:
    """Verify that settings refuse escalation.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        section: Section value used by the test case.
        patch: Patch value used by the test case.
    """
    store = Store(tmp_path)
    w = store.create_workspace('no escalation')
    service = AgentService(store, AccessPolicy(allow_write=True, allow_config_write=True))
    try:
        before = service.call('settings_get', w, section=section)
        with pytest.raises(AgentError) as caught:
            service.call('settings_update', w, section=section, values=patch, expected_revision=before['settings_revision'])
        assert caught.value.code == 'requires_local_admin'
        assert service.call('settings_get', w, section=section) == before
    finally:
        service.close()
        store.close()


def test_only_local_admin_can_reenable_disabled_access(tmp_path: Path) -> None:
    """Verify that only local admin can reenable disabled access.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.agent.contracts import AgentSettings
    store = Store(tmp_path)
    w = store.create_workspace('disabled')
    AgentSettings(enabled=False, allow_write=False).save(store, w)
    local = AgentService(store, AccessPolicy(allow_write=True, allow_config_write=True, allow_admin=True))
    ordinary = AgentService(store, AccessPolicy(allow_write=True, allow_config_write=True))
    try:
        with pytest.raises(AgentError):
            ordinary.call('settings_get', w, section='agent_access')
        before = local.call('settings_get', w, section='agent_access')
        local.call('settings_update', w, section='agent_access', values={'enabled': True, 'allow_write': True}, expected_revision=before['settings_revision'])
        assert ordinary.call('settings_get', w, section='agent_access')['values']['enabled']
        with pytest.raises(AgentError):
            create_server(local)
    finally:
        local.close()
        ordinary.close()
        store.close()


def test_settings_schema_pins_ui_fields_ranges_and_read_only_process_cap(tmp_path: Path) -> None:
    """Verify that settings schema pins ui fields ranges and read only process cap.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.settings_service import SECTIONS
    expected_ranges = {'max_file_mb': (1, 100), 'max_files': (1, 100000), 'parse_workers': (1, 8),
        'llm_concurrency': (1, 4), 'llm_chunk_chars': (500, 100000), 'csv_sample_rows': (0, 100),
        'graph_limit': (10, 1000), 'traversal_depth': (1, 30), 'tree_expansion_depth': (0, 30),
        'graph_edge_width': (1, 5), 'max_context_chars': (500, 100000), 'llm_retention_days': (1, 3650),
        'max_chars': (512, 100000), 'min_lineage_confidence': (0, 1)}
    store = Store(tmp_path)
    w = store.create_workspace('schemas')
    service = AgentService(store, AccessPolicy(allow_write=True, allow_config_write=True))
    try:
        properties = {}
        for section, model in SECTIONS.items():
            result = service.call('settings_schema', w, section=section)
            assert set(result['schema']['properties']) == set(model.model_fields)
            assert result['defaults'] == model().model_dump() and result['llm_process_cap'] == 8
            properties.update(result['schema']['properties'])
        for field, (minimum, maximum) in expected_ranges.items():
            assert (properties[field]['minimum'], properties[field]['maximum']) == (minimum, maximum)
        before = service.call('settings_get', w, section='resources')
        with pytest.raises(AgentError):
            service.call('settings_update', w, section='resources', values={'llm_process_cap': 100, 'allow_admin': True},
                expected_revision=before['settings_revision'])
        assert service.call('settings_get', w, section='resources') == before
    finally:
        service.close()
        store.close()
