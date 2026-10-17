"""Reproducible CLI/MCP/shared-report parity on the supplied ZIPs, in a NEW home only."""
import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typer.testing import CliRunner

from dataforge.agent.contracts import AccessPolicy
from dataforge.agent.mcp_server import create_server
from dataforge.agent.service import AgentService
from dataforge.cli import app
from dataforge.graph import LineageGraph
from dataforge.reporting import data_dictionary
from dataforge.store import Store


def verify(home):
    if home.exists():
        raise ValueError('Verification requires a new disposable home')
    runner = CliRunner()
    root = Path('tests/sample_data').resolve()
    base = ['--home', str(home), '--json', '--allow-write', '--allowed-root', str(root),
            '--max-depth', '30', '--max-chars', '100000', '--limit', '500', '--collapse-temporary']

    def cli(*args):
        result = runner.invoke(app, [*base, *args])
        if result.exit_code:
            raise AssertionError(result.output)
        return json.loads(result.output)

    results = {}
    for extension in ('sql', 'sas'):
        workspace = cli('workspace', 'create', 'Parity ' + extension.upper())['workspace_id']
        archive = root / f'dataforge_{extension}_lineage_test_project.zip'
        imported = cli('ingest', str(archive), '-w', workspace, '--extensions', extension)
        assert imported['result']['accepted'] == 86
        cold = cli('lineage', 'build', '-w', workspace)
        warm = cli('lineage', 'build', '-w', workspace)
        assert cold['result']['analyzed'] == warm['result']['cached'] == 86
        store = Store(home)
        service = AgentService(store, AccessPolicy(allow_write=True, workspaces=(workspace,)))
        try:
            # Owner reopened after each CLI invocation. These reads do not reparse any script.
            store.set_setting(workspace, 'agent_access', {'max_chars': 100000})
            graph = LineageGraph(store.assets(workspace), store.edges(workspace)).simplified()
            with ZipFile(archive) as zipped:
                manifest = json.loads(zipped.read(next(n for n in zipped.namelist() if n.endswith('expected/lineage_manifest.json'))))
                for source in store.files(workspace):
                    original = zipped.read(source['relative_path'])
                    assert store.original(source['file_id']) == original
                    assert hashlib.sha256(original).hexdigest() == source['content_hash']
            expected = {(source, a['target']) for a in manifest['assets'] for source in a['inputs']}
            persistent_names = {a['target'] for a in manifest['assets']}
            assert len(persistent_names) == 85
            assert persistent_names <= {a['name'] for a in store.assets(workspace) if not a['temporary']}
            logical = {(graph.nodes[s]['name'], graph.nodes[t]['name']) for s, t in graph.graph.edges}
            assert logical == expected and len(logical) == 128
            options = {'limit': 500, 'max_depth': 30, 'max_chars': 100000, 'collapse_temporary': True}
            direct = service.call('lineage', workspace, asset='pub.all_kpis', options=options)
            roots = {a['target'] for a in manifest['assets'] if a['stage'] == 'src'}
            assert len(roots) == 16 and roots <= {a['name'] for a in direct['items']} and direct['complete']
            layers = {a['name'].split('.')[0] for a in direct['items']} | {'pub'}
            assert layers == {'src', 'ext', 'stg', 'core', 'mart', 'rpt', 'pub'}
            server = create_server(service)
            actual = asyncio.run(server.call_tool('get_lineage', {'workspace_id': workspace, 'asset': 'pub.all_kpis', 'options': options}))
            assert not actual.isError and actual.structuredContent == direct
            dictionary = service.call('dictionary', workspace, options=options)
            assert dictionary['items'] == data_dictionary(store, workspace)[:dictionary['count']]
            validation = asyncio.run(server.call_tool('validate_stored_lineage', {'workspace_id': workspace, 'options': options}))
            assert not validation.isError and validation.structuredContent['invalid_count'] == 0
            temp = sum(a['temporary'] for a in store.assets(workspace))
            physical = len(store.edges(workspace))
            assert temp == (16 if extension == 'sas' else 0)
            assert physical == (144 if extension == 'sas' else 128)
            results[extension] = {'workspace_id': workspace, 'scripts': 86, 'persistent_tables': len(persistent_names), 'logical_edges': 128,
                'physical_edges': physical, 'temporary': temp, 'sources_reached': len(roots), 'layers': len(layers),
                'warm_cached': 86, 'originals_exact': True, 'service_cli_mcp_dictionary_evidence': 'passed'}
        finally:
            service.close()
            store.close()
        assert cli('lineage', 'upstream', 'pub.all_kpis', '-w', workspace) == direct

    async def stdio_check():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'dataforge.cli', '--home', str(home), 'mcp'])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert 'get_data_dictionary' in {t.name for t in tools.tools}
                result = await session.call_tool('get_capabilities', {})
                assert not result.isError and result.structuredContent['total'] == 46
    asyncio.run(stdio_check())
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    results = verify(args.home.resolve())
    args.output.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(results, indent=2))
