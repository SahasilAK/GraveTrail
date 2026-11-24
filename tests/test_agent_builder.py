import asyncio
import base64
import json
from contextlib import closing
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy, AgentError, AgentSettings
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.store import Store


def cli(home: Path, *arguments: str) -> dict:
    result = CliRunner().invoke(app, ['--home', str(home), '--json', *arguments])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def artifact_bytes(service: AgentService, workspace: str, artifact: dict) -> bytes:
    chunk = service.call('artifact_read', workspace, artifact_id=artifact['artifact_id'])
    return base64.b64decode(chunk['data'])


def test_source_and_schema_import_from_approved_files(tmp_path: Path) -> None:
    home = tmp_path / 'home'
    source_root = tmp_path / 'files'
    source_root.mkdir()
    sql = source_root / 'example.sql'
    sql.write_text('select 1;', encoding='utf-8')
    csv = source_root / 'values.csv'
    csv.write_text('id\n1\n', encoding='utf-8')
    schema = source_root / 'schema.json'
    schema.write_text('{"tables":[{"name":"Orders","columns":[{"name":"id","data_type":"INT"}]}]}', encoding='utf-8')
    with closing(Store(home)) as store:
        workspace = store.create_workspace('Design')

    write = ('--allow-write', '--allowed-root', str(source_root))
    cli(home, *write, 'ingest', str(sql), '--file', str(csv), '-w', workspace)
    inventory = cli(home, 'source', 'list', '-w', workspace, '--query', 'pending')['items']
    files = {item['relative_path']: item['file_id'] for item in inventory}
    assert set(files) == {'example.sql', 'values.csv'}
    dialect = (*write, 'source', 'dialect', files['example.sql'], '-w', workspace)
    assert cli(home, *dialect, '--dialect', 'postgres')['sql_dialect_override'] == 'postgres'
    assert cli(home, *dialect)['sql_dialect_override'] is None
    exported = cli(home, *write, 'export', 'report', '-w', workspace, '--kind', 'inventory', '--query', 'example.sql')

    with closing(Store(home)) as store, closing(AgentService(store, AccessPolicy(
        allow_write=True, import_roots=(str(source_root),),
    ))) as service:
        inventory = json.loads(artifact_bytes(service, workspace, exported))
        assert [item['relative_path'] for item in inventory] == ['example.sql']
        selection = {'paths': [str(schema)]}
        preview = service.call('builder_schema_preview', workspace, **selection)
        assert preview['table_count'] == 1
        assert service.call('builder_inspect', workspace)['table_count'] == 0
        schema.write_text(schema.read_text(encoding='utf-8').replace('Orders', 'People'), encoding='utf-8')
        with pytest.raises(AgentError, match='changed'):
            service.call('builder_schema_import', workspace, expected_pin=preview['pin'], **selection)
        preview = service.call('builder_schema_preview', workspace, **selection)
        assert service.call('builder_schema_import', workspace, expected_pin=preview['pin'], **selection)['revision'] == 1
        exported = service.call('builder_export', workspace, kind='schemas', format='json', role='source')
        assert json.loads(artifact_bytes(service, workspace, exported))['tables'][0]['name'] == 'People'
        AgentSettings(allow_source=False).save(store, workspace)
        with pytest.raises(AgentError) as exc:
            artifact_bytes(service, workspace, exported)
        assert exc.value.code == 'forbidden'


def test_builder_canvas_snapshot_and_local_schema_deletion(tmp_path: Path) -> None:
    home = tmp_path / 'home'
    with closing(Store(home)) as store:
        workspace = store.create_workspace('Design')
        with closing(AgentService(store, AccessPolicy(allow_write=True, workspaces=(workspace,)))) as service:
            server = create_server(service)
            table = {'id': 'orders', 'name': 'Orders', 'position': {'x': 42, 'y': 71},
                     'color': '#445566', 'columns': [{'id': 'id', 'name': 'id', 'data_type': 'INT'}]}

            async def author_snapshot() -> str:
                result = await server.call_tool('apply_builder_document', {'workspace_id': workspace,
                    'expected_revision': 0, 'document': {'tables': [table]}})
                assert not result.isError and result.structuredContent['revision'] == 1
                stale = await server.call_tool('apply_builder_document', {'workspace_id': workspace,
                    'expected_revision': 0, 'document': {'tables': []}})
                assert stale.isError and stale.structuredContent['error']['code'] == 'conflict'
                result = await server.call_tool('save_builder_snapshot', {'workspace_id': workspace,
                    'expected_revision': 1, 'name': 'Orders design', 'clear': True})
                assert not result.isError and result.structuredContent['revision'] == 2
                return result.structuredContent['work_id']

            work_id = asyncio.run(author_snapshot())
            assert service.call('builder_inspect', workspace)['items'][0]['position'] is None
            saved = service.call('builder_inspect', workspace, work_id=work_id)['items'][0]
            assert saved['position'] == table['position'] and saved['color'] == table['color']
            with pytest.raises(AgentError):
                service.call('builder_export', workspace, format='svg')
            svg = service.call('builder_export', workspace, format='svg', work_id=work_id)
            image = artifact_bytes(service, workspace, svg)
            assert all(value in image for value in (b'translate(42.0 71.0)', b'#445566', b'Orders'))
            png = service.call('builder_export', workspace, format='png', work_id=work_id)
            assert artifact_bytes(service, workspace, png).startswith(b'\x89PNG\r\n\x1a\n')
            assert service.call('builder_work_load', workspace, expected_revision=2, work_id=work_id)['revision'] == 3
            preview = asyncio.run(server.call_tool('preview_builder_table_deletion', {'workspace_id': workspace,
                'table_ids': ['orders']}))
            assert not preview.isError and preview.structuredContent['affected_tables'] == 1
            with pytest.raises(AgentError) as exc:
                service.call('builder_delete', workspace, expected_revision=3,
                             table_ids=['orders'], confirm='DELETE BUILDER TABLES')
            assert exc.value.code == 'requires_local_admin'

    deleted = cli(home, '--allow-write', '--allow-config-write', '--allow-admin', 'builder', 'delete-tables',
                  'orders', '-w', workspace, '--revision', '3', '--confirm', 'DELETE BUILDER TABLES')
    assert deleted['table_count'] == 0
    works = cli(home, 'builder', 'inspect', '-w', workspace, '--view', 'works')['items']
    assert works[0]['id'] == work_id
