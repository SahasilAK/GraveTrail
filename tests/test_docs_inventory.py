"""The developer inventory covers first-party files without importing application code."""
from pathlib import Path

from scripts.docs import inventory


def test_published_inventory_is_current_and_covers_first_party_files() -> None:
    paths = set(inventory.inventory_paths(inventory.ROOT))
    assert {
        "app.py", "src/dataforge/services.py", "src/dataforge/agent/mcp_server.py",
        "src/dataforge/dbt/analysis.py", "src/dataforge/parsers/sas.py", "ui/pages/analysis.py",
        "scripts/docs/inventory.py", "tests/test_docs_inventory.py", "tests/test_ai_full_build.py",
        "tests/fixtures/dbt/input/models/py_orders.py", "prompts/project_lineage/extract.md",
        "prompts/schemas/project_lineage_wire_response.json", ".github/workflows/tests.yml",
        "ui/streamlit.toml", "scripts/build/windows_installer.ps1", "pyproject.toml", "uv.lock",
    } <= paths
    git_files = inventory.git_paths(inventory.ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    assert {name for name in git_files if name.endswith(".py")
            and name.startswith(("src/", "ui/", "scripts/", "tests/"))
            and (inventory.ROOT / name).is_file()} <= paths
    assert not any("__pycache__" in path or path.endswith("KNOWLEDGE.md") for path in paths)
    output = inventory.ROOT / inventory.OUTPUT
    assert inventory.write_inventory(inventory.ROOT, output, check=True), "Regenerate source-inventory.md"
    rendered = output.read_text(encoding="utf-8")
    baseline = set(inventory.git_paths(inventory.ROOT, "ls-tree", "-r", "--name-only", "-z", inventory.BASELINE))
    for name in paths:
        expected = (f"[`{name}`]({inventory.REPOSITORY}/blob/{inventory.BASELINE}/{name})"
                    if name in baseline else f"`{name}` **new**")
        assert rendered.count(expected) == 1, name


def test_python_details_parse_without_executing_source(tmp_path: Path) -> None:
    source = tmp_path / "poison.py"
    source.write_text('''"""Exact source | summary <safe>."""
raise RuntimeError("this module must never execute")
VALUE = 3
def public(value):
    return value
class Contract:
    pass
def _private():
    pass
''', encoding="utf-8")
    summary, names = inventory.python_details(source)
    assert summary == "Exact source | summary <safe>."
    assert names == "`VALUE`, `public`, `Contract`"
    assert inventory.cell(summary) == "Exact source \\| summary &lt;safe&gt;."
