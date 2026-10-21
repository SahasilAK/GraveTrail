import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.store import Store


def test_capabilities_cover_inventory(tmp_path: Path) -> None:
    """Verify that capabilities cover inventory.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    with_store = Store(tmp_path)
    service = AgentService(with_store)
    try:
        result = service.call('capabilities', options={'max_chars': 100000})
        items = list(result['items'])
        cursor = result['next_cursor']
        while cursor:
            following = service.call('capabilities', options={'cursor': cursor, 'max_chars': 100000})
            items.extend(following['items'])
            cursor = following['next_cursor']
        ids = [r['capability_id'] for r in items]
        expected = {f'{prefix}{n:02}' for prefix, count in
                    [('P', 5), ('A', 7), ('S', 10), ('W', 5), ('V', 4),
                     ('R', 7), ('E', 3), ('C', 5), ('M', 1), ('I', 1)] for n in range(1, count + 1)}
        assert set(ids) == expected | {'DBT01'} and len(ids) == 49
        assert all({'cli', 'mcp', 'effects', 'restriction', 'availability'} <= r.keys() for r in result['items'])
        server = create_server(service)
        actual = asyncio.run(server.call_tool('get_capabilities', {'options': {'max_chars': 100000}}))
        assert actual.structuredContent == result
        assert not actual.isError
    finally:
        service.close()
        with_store.close()
    result = CliRunner().invoke(app, ['--home', str(tmp_path), '--json', 'capabilities'])
    assert result.exit_code == 0, result.output


def test_independent_permissions_and_scoped_admin() -> None:
    """Verify that independent permissions and scoped admin."""
    policy = AccessPolicy(allow_write=True)
    for operation in ('config', 'network', 'application', 'admin'):
        with pytest.raises(AgentError):
            policy.require(operation)
    scoped = AccessPolicy(allow_write=True, allow_config_write=True, allow_admin=True, workspaces=('one',))
    with pytest.raises(AgentError):
        scoped.require('admin')
