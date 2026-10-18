"""Publication boundaries and CLI/MCP documentation must match exposed interfaces."""
import asyncio
import re
from pathlib import Path

import pytest


def reference_rows(document, section):
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


def test_cli_guide_lists_every_registered_command_group_and_option():
    import typer.main

    from dataforge.cli import app

    root = typer.main.get_command(app)
    commands, groups = {}, set()

    def walk(group, prefix=()):
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
    def flags(row):
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


def test_mcp_guide_lists_every_registered_tool_resource_prompt_and_input(tmp_path):
    from dataforge.agent.mcp_server import create_server
    from dataforge.agent.service import AgentService
    from dataforge.store import Store

    store = Store(tmp_path / "home")
    service = AgentService(store)

    async def check():
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


def test_publication_filter_excludes_unlisted_files_and_requires_sources(tmp_path):
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


def test_document_routes_do_not_collide_on_case_insensitive_hosts():
    from scripts.docs.hooks import page_output

    outputs = {page_output(name) for name in ("ARCHITECTURE.md", "architecture/overview.md", "index.md")}
    assert outputs == {"architecture/index.html", "architecture/overview/index.html", "index.html"}


def test_site_links_validate_project_prefix_fragments_and_missing_targets(tmp_path):
    from scripts.docs.validate import inspect_site

    (tmp_path / "guide").mkdir()
    (tmp_path / "index.html").write_text(
        '<a href="/dataforge-engineering-hub/guide/#install">Install</a>', encoding="utf-8"
    )
    (tmp_path / "guide/index.html").write_text('<h1 id="install">Install</h1>', encoding="utf-8")
    assert inspect_site(tmp_path, "/dataforge-engineering-hub/") == []
    (tmp_path / "index.html").write_text(
        '<a href="guide/#missing">Bad</a><img src="/assets/missing.png">', encoding="utf-8"
    )
    errors = inspect_site(tmp_path, "/dataforge-engineering-hub/")
    assert any("#missing" in error for error in errors)
    assert any("project prefix" in error for error in errors)


def test_output_inventory_rejects_runtime_and_unexpected_files(tmp_path):
    from scripts.docs.validate import inspect_inventory

    (tmp_path / "index.html").write_text("Public", encoding="utf-8")
    assert inspect_inventory(tmp_path, {"index.html"}) == []
    (tmp_path / "workspace.duckdb").write_bytes(b"runtime")
    assert any("workspace.duckdb" in error for error in inspect_inventory(tmp_path, {"index.html"}))
    (tmp_path / "index.html").unlink()
    assert any("Missing" in error for error in inspect_inventory(tmp_path, {"index.html"}))
