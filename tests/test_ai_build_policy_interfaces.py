import asyncio

from typer.testing import CliRunner

from dataforge.cli import app


def test_cli_exposes_files_parallel_and_project_limits():
    from typer.main import get_command
    result = CliRunner().invoke(app, ['lineage', 'build', '--help'], color=False)
    assert result.exit_code == 0
    command = get_command(app).commands['lineage'].commands['build']
    flags = {flag for p in command.params for flag in [*p.opts, *p.secondary_opts]}
    for flag in ('--max-files-per-request', '--max-parallel-requests', '--max-context-chars', '--project-max-provider-attempts', '--auto-continue'):
        assert flag in flags


def test_mcp_preview_and_build_share_policy_fields(tmp_path):
    from dataforge.agent.mcp_server import create_server
    from dataforge.agent.service import AgentService
    from dataforge.store import Store
    store = Store(tmp_path)
    server = create_server(AgentService(store))
    tools = asyncio.run(server.list_tools())
    for name in ('start_lineage_analysis', 'preview_project_analysis'):
        fields = next(t for t in tools if t.name == name).inputSchema['properties']
        assert {'max_files_per_request', 'max_parallel_requests', 'max_context_chars', 'auto_continue',
                'project_max_provider_attempts', 'project_max_output_tokens_total', 'project_max_seconds'} <= fields.keys()
    store.close()
