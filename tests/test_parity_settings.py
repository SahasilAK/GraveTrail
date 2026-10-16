import asyncio
import json

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.store import Store


def test_typed_sections_atomic_conflicts_and_mcp(tmp_path):
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
def test_settings_refuse_escalation(tmp_path, section, patch):
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
