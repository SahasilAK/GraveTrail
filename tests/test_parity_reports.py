import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AgentError, AgentSettings
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_reports_dictionary_schema_history_and_cli(tmp_path: Path) -> None:
    """Verify that reports dictionary schema history and cli.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    w = store.create_workspace('reports')
    Importer(store, w).files([('q.sql', b'create table raw.a (id integer);\ncreate table mart.x as select id from raw.a;')], {'.sql'})
    first = analyze(store, w)['run_id']
    second = analyze(store, w)['run_id']
    service = AgentService(store)
    try:
        dictionary = service.call('dictionary', w)
        assert any(r['asset'] == 'raw.a' and r['type'] == 'INT' for r in dictionary['items'])
        schema = asyncio.run(create_server(service).call_tool('get_asset_schema', {'workspace_id': w, 'asset': 'raw.a'}))
        assert not schema.isError and schema.structuredContent['columns'][0]['name'] == 'id'
        assert service.call('runs_compare', w, before=first, after=second)['comparison']['added_assets'] == []
        assert service.call('lineage_validate', w)['invalid_count'] == 0
        matches = service.call('search_code', w, query='select', include_matches=True)
        assert matches['items'][0]['line'] == 2
        search_args = ['--home', str(tmp_path), '--json', 'source', 'search', 'select', '-w', w, '--include-matches']
        cli_matches = CliRunner().invoke(app, search_args)
        assert cli_matches.exit_code == 0 and json.loads(cli_matches.output)['items'][0]['line'] == 2
        AgentSettings(allow_source=False).save(store, w)
        denied = CliRunner().invoke(app, search_args)
        assert denied.exit_code == 3 and json.loads(denied.output)['error']['code'] == 'forbidden'
        foreign = store.create_workspace('other')
        with pytest.raises(AgentError):
            service.call('run_get', foreign, run_id=first)
    finally:
        service.close()
        store.close()
    result = CliRunner().invoke(app, ['--home', str(tmp_path), '--json', 'workspace', 'health', '-w', w])
    assert result.exit_code == 0 and json.loads(result.output)['counts']['source_files'] == 1
