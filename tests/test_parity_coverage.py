import asyncio
import json
from pathlib import Path

import typer.main
from typer.testing import CliRunner

from dataforge.agent.capabilities import capability_catalog
from dataforge.agent.contracts import AccessPolicy
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.store import Store


def test_checked_capabilities_resolve_to_actual_cli_and_mcp(tmp_path):
    expected = json.loads(Path('tests/fixtures/parity_capabilities.json').read_text(encoding='utf-8'))
    store = Store(tmp_path)
    service = AgentService(store)
    try:
        entries = capability_catalog(service)
        assert len(entries) == 46 and {e['capability_id'] for e in entries} == set(expected)
        cli = typer.main.get_command(app)
        tools = {t.name for t in asyncio.run(create_server(service).list_tools())}
        for entry in entries:
            contract = expected[entry['capability_id']]
            assert entry['availability'] in {'implemented', 'policy_restricted'}
            assert all(entry[key] == value for key, value in contract.items())
            assert set(entry['mcp']) <= tools
            if entry['availability'] == 'policy_restricted':
                assert entry['restriction']
            for route in entry['cli']:
                command = cli
                for part in route:
                    assert part in command.commands, route
                    command = command.commands[part]
                result = CliRunner().invoke(app, [*route, '--help'])
                assert result.exit_code == 0, result.output
    finally:
        service.close()
        store.close()


def test_every_mutation_and_network_mcp_tool_denies_read_only_launch(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('read only')
    service = AgentService(store, AccessPolicy(workspaces=(w,)))
    server = create_server(service)

    async def check():
        for tool in await server.list_tools():
            if tool.annotations.readOnlyHint:
                continue
            schema = tool.inputSchema
            arguments = {}
            for name in schema.get('required', []):
                field = schema['properties'][name]
                if name == 'workspace_id':
                    value = w
                elif 'enum' in field:
                    value = field['enum'][0]
                elif field.get('type') == 'object':
                    value = {}
                elif field.get('type') == 'array':
                    value = ['sql']
                elif field.get('type') in {'integer', 'number'}:
                    value = 1
                else:
                    value = 'test'
                arguments[name] = value
            result = await server.call_tool(tool.name, arguments)
            assert result.isError, tool.name
            assert result.structuredContent['error']['code'] in {'forbidden', 'requires_local_admin', 'network_not_allowed'}, (tool.name, result)
    try:
        asyncio.run(check())
        assert not store.files(w) and not store.rows('SELECT * FROM llm_profiles')
    finally:
        service.close()
        store.close()
