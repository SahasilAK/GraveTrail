"""Publication boundaries and CLI/MCP documentation must match exposed interfaces."""
import asyncio
import re
from pathlib import Path
from typing import Any

import pytest


def reference_rows(document: Any, section: Any) -> Any:
    """Handle reference rows for the test scenario.

    Args:
        document: Document value used by the test case.
        section: Section value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    text = (Path(__file__).resolve().parents[1] / "docs" / document).read_text(encoding="utf-8")
    start, end = f"<!-- {section}:start -->", f"<!-- {section}:end -->"
    assert text.count(start) == text.count(end) == 1, f"Missing or duplicate {section} reference"
    body = text.split(start, 1)[1].split(end, 1)[0]
    rows = {}
    for line in body.splitlines():
        if match := re.match(r"\| `([^`]+)` \|", line):
            assert match[1] not in rows, f"Duplicate documentation row: {match[1]}"
            rows[match[1]] = line.split("|", 2)[2]
    return rows


def test_cli_guide_lists_every_registered_command_group_and_option() -> None:
    """Verify that cli guide lists every registered command group and option."""
    import typer.main

    from dataforge.cli import app

    root = typer.main.get_command(app)
    commands, groups = {}, set()

    def walk(group: Any, prefix: Any=()) -> None:
        """Handle walk for the test scenario.

        Args:
            group: Group value used by the test case.
            prefix: Prefix value used by the test case.
        """
        for name, command in group.commands.items():
            route = (*prefix, name)
            if hasattr(command, "commands"):
                groups.add(" ".join(route))
                walk(command, route)
            else:
                commands[" ".join(route)] = command

    walk(root)
    rows = reference_rows("CLI_GUIDE.md", "cli-commands")
    assert set(rows) == set(commands)
    assert set(reference_rows("CLI_GUIDE.md", "cli-groups")) == groups
    def flags(row: Any) -> Any:
        """Handle flags for the test scenario.

        Args:
            row: Row value used by the test case.

        Returns:
            Value produced for the test scenario.
        """
        return set(re.findall(r"`(-{1,2}[\w-]+)`", row))

    for route, command in commands.items():
        params = command.get_params(command.context_class(command))
        expected = {flag for p in params if p.param_type_name == "option" for flag in p.opts + p.secondary_opts}
        assert flags(rows[route]) == expected, route
        arguments = [p.name.upper() + ("..." if p.nargs == -1 else "")
                     for p in params if p.param_type_name == "argument"]
        assert re.findall(r"`([^`]+)`", rows[route].split("|")[0]) == arguments, route
    params = root.get_params(root.context_class(root))
    expected = {flag for p in params for flag in p.opts + p.secondary_opts}
    rows = reference_rows("CLI_GUIDE.md", "cli-options")
    documented = set(rows)
    for row in rows.values():
        documented.update(flags(row))
    assert documented == expected


def test_mcp_guide_lists_every_registered_tool_resource_prompt_and_input(tmp_path: Path) -> None:
    """Verify that mcp guide lists every registered tool resource prompt and input.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.agent.mcp_server import create_server
    from dataforge.agent.service import AgentService
    from dataforge.store import Store

    store = Store(tmp_path / "home")
    service = AgentService(store)

    async def check() -> None:
        """Handle check for the test scenario."""
        server = create_server(service)
        tools = await server.list_tools()
        rows = reference_rows("MCP_INTEGRATION.md", "mcp-tools")
        assert set(rows) == {tool.name for tool in tools}
        for tool in tools:
            required, optional, *_ = rows[tool.name].split("|")
            required = set(re.findall(r"`([^`]+)`", required))
            optional = set(re.findall(r"`([^`]+)`", optional))
            assert required == set(tool.inputSchema.get("required", [])), tool.name
            assert required | optional == set(tool.inputSchema.get("properties", {})), tool.name
        resources = await server.list_resources()
        templates = await server.list_resource_templates()
        assert set(reference_rows("MCP_INTEGRATION.md", "mcp-resources")) == (
            {str(resource.uri) for resource in resources} | {template.uriTemplate for template in templates})
        prompts = await server.list_prompts()
        rows = reference_rows("MCP_INTEGRATION.md", "mcp-prompts")
        assert set(rows) == {prompt.name for prompt in prompts}
        for prompt in prompts:
            required, optional, *_ = rows[prompt.name].split("|")
            assert set(re.findall(r"`([^`]+)`", required)) == {arg.name for arg in prompt.arguments or [] if arg.required}
            assert set(re.findall(r"`([^`]+)`", optional)) == {arg.name for arg in prompt.arguments or [] if not arg.required}

    try:
        asyncio.run(check())
    finally:
        service.close()
        store.close()


def test_publication_filter_excludes_unlisted_files_and_requires_sources(tmp_path: Path) -> None:
    """Verify that publication filter excludes unlisted files and requires sources.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from scripts.docs.hooks import public_files

    (tmp_path / "index.md").write_text("# Public", encoding="utf-8")
    (tmp_path / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.env").write_text("PRIVATE", encoding="utf-8")
    assert public_files(tmp_path, {"index.md", "logo.svg"}) == {"index.md", "logo.svg"}
    with pytest.raises(ValueError, match="missing"):
        public_files(tmp_path, {"missing.md"})
    with pytest.raises(ValueError, match="Unsafe"):
        public_files(tmp_path, {"secret.env"})
    with pytest.raises(ValueError, match="Unsafe"):
        public_files(tmp_path, {"../outside.md"})
    (tmp_path / "KNOWLEDGE.md").write_text("Internal", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe"):
        public_files(tmp_path, {"KNOWLEDGE.md"})


def test_only_reviewed_html_example_can_be_published(tmp_path: Path) -> None:
    """A reviewed digest admits one fixture, never arbitrary executable HTML."""
    from scripts.docs.hooks import public_files

    name = 'assets/examples/lineage.html'
    source = Path('docs') / name
    target = tmp_path / name
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())
    assert public_files(tmp_path, {name}) == {name}
    target.write_bytes(source.read_bytes() + b'<script src="https://example.org/x.js"></script>')
    with pytest.raises(ValueError, match='reviewed HTML'):
        public_files(tmp_path, {name})
    (tmp_path / 'arbitrary.html').write_text('<script>alert(1)</script>', encoding='utf-8')
    with pytest.raises(ValueError, match='Unsafe'):
        public_files(tmp_path, {'arbitrary.html'})


def test_output_inventory_rejects_runtime_and_unexpected_files(tmp_path: Path) -> None:
    """Verify that output inventory rejects runtime and unexpected files.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from scripts.docs.validate import inspect_inventory

    (tmp_path / "index.html").write_text("Public", encoding="utf-8")
    assert inspect_inventory(tmp_path, {"index.html"}) == []
    (tmp_path / "workspace.duckdb").write_bytes(b"runtime")
    assert any("workspace.duckdb" in error for error in inspect_inventory(tmp_path, {"index.html"}))
    (tmp_path / "index.html").unlink()
    assert any("Missing" in error for error in inspect_inventory(tmp_path, {"index.html"}))
