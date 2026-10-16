import asyncio
import json

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AgentError, AgentSettings
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def test_reports_dictionary_schema_history_and_cli(tmp_path):
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
        AgentSettings(allow_source=False).save(store, w)
        with pytest.raises(AgentError):
            service.call('search_code', w, query='select', include_matches=True)
        foreign = store.create_workspace('other')
        with pytest.raises(AgentError):
            service.call('run_get', foreign, run_id=first)
    finally:
        service.close()
        store.close()
    result = CliRunner().invoke(app, ['--home', str(tmp_path), '--json', 'workspace', 'health', '-w', w])
    assert result.exit_code == 0 and json.loads(result.output)['counts']['source_files'] == 1


def test_cli_search_matches_requires_source_permission(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace('search')
    Importer(store, w).files([('a.sql', b'select id from raw.a;')], {'.sql'})
    store.close()
    result = CliRunner().invoke(app, ['--home', str(tmp_path), '--json', 'source', 'search', 'select', '-w', w, '--include-matches'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['items'][0]['line'] == 1
