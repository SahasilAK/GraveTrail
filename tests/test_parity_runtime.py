import asyncio
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.store import Store


def test_application_theme_logging_scope_and_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that application theme logging scope and setup.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    config = tmp_path / 'config.toml'
    config.write_text('[server]\nport=1234 # preserved\n[theme]\nfont="serif"\n', encoding='utf-8')
    monkeypatch.setenv('DATAFORGE_THEME_CONFIG', str(config))
    store = Store(tmp_path / 'home')
    w = store.create_workspace('runtime')
    owner = AgentService(store, AccessPolicy(allow_write=True, allow_config_write=True, allow_application_config=True))
    try:
        presets = owner.call('theme_list')
        assert len(presets['items']) == 11
        result = owner.call('theme_apply', name='Arctic Mint')
        assert result['configured'] == 'Arctic Mint' and result['loaded'] is None and result['reload_required']
        assert '# preserved' in config.read_text() and 'serif' in config.read_text()
        server = create_server(owner)
        actual = asyncio.run(server.call_tool('update_application_logging', {'level': 'WARNING'}))
        assert not actual.isError and store.setting('__application__', 'log_level') == 'WARNING'
        setup = owner.call('agent_setup', w)
        assert setup['stdio']['command'] == sys.executable and w in setup['stdio']['args']
        test = owner.call('agent_self_test', w)
        assert test['passed'] and test['method'] == 'in_process_mcp_handler'
        restricted = AgentService(store, AccessPolicy(allow_write=True, allow_config_write=True, allow_application_config=True, workspaces=(w,)))
        try:
            with pytest.raises(AgentError):
                restricted.call('theme_apply', name='Ocean dark')
            assert 'home' not in restricted.call('runtime_info', w)
        finally:
            restricted.close()
    finally:
        owner.close()
        store.close()
    result = CliRunner().invoke(app, ['--home', str(tmp_path / 'home'), '--json', 'application', 'logging', 'get'])
    assert result.exit_code == 0 and 'WARNING' in result.output
