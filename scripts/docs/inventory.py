"""Generate the first-party source inventory using Git paths and Python AST only."""
from __future__ import annotations

import argparse
import ast
import html
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "1864dc8887ac8342a8ef8b369cc8a2e8b5d2e414"
REPOSITORY = "https://github.com/SahasilAK/GraveTrail"
OUTPUT = "docs/development/source-inventory.md"
TREES = ("src/", "ui/", "scripts/", "tests/", "prompts/", ".github/", ".streamlit/")
ROOT_FILES = {
    "app.py", "pyproject.toml", "uv.lock", "Dockerfile", "compose.yaml",
    "dependency-overrides.txt", ".dockerignore", ".gitattributes", ".gitignore", ".gitleaks.toml",
}
GROUPS = (
    "Entry points and package", "Static parsing and identity", "Storage and configuration",
    "Graphs, columns and exports", "AI and provider services", "dbt",
    "CLI and MCP automation", "Streamlit UI", "Prompts and response schemas",
    "Verification and release tooling", "Documentation tooling", "Build and packaging tooling",
    "Continuous integration and repository templates", "Runtime and development configuration",
    "Test support and fixtures", "Tests: AI and providers", "Tests: dbt", "Tests: automation",
    "Tests: parsing, graph and storage", "Tests: UI, packaging and repository",
)


def git_paths(root: Path, *arguments: str) -> list[str]:
    """Read NUL-delimited Git paths without executing any application module."""
    result = subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True,
    )
    return result.stdout.decode("utf-8").rstrip("\0").split("\0") if result.stdout else []


def inventory_paths(root: Path) -> list[str]:
    """Select existing first-party files, including uncommitted nonignored additions."""
    candidates = git_paths(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted({
        name for name in candidates
        if (name in ROOT_FILES or name.startswith(TREES))
        and Path(name).name != "KNOWLEDGE.md"
        and not any(part in {"__pycache__", ".pytest_cache", ".ruff_cache"} for part in Path(name).parts)
        and (root / name).is_file()
    })


def subsystem(name: str) -> str:
    """Assign each inventory path to one stable navigation section."""
    stem = Path(name).stem
    if name.startswith("tests/"):
        if not stem.startswith("test_"):
            return "Test support and fixtures"
        if stem.startswith(("test_ai_", "test_llm", "test_provider", "test_gateway", "test_focused_")):
            return "Tests: AI and providers"
        if stem.startswith("test_dbt"):
            return "Tests: dbt"
        if stem.startswith(("test_agent", "test_parity")):
            return "Tests: automation"
        if stem.startswith(("test_sql", "test_sas", "test_parser", "test_store", "test_ingestion",
                            "test_graph", "test_column", "test_transformation", "test_schema", "test_lineage",
                            "test_cleanup", "test_temporary", "test_maintenance", "test_job", "test_exports",
                            "test_excel", "test_hardening", "test_connections", "test_storage")):
            return "Tests: parsing, graph and storage"
        return "Tests: UI, packaging and repository"
    if name.startswith("src/dataforge/agent/"):
        return "CLI and MCP automation"
    if name.startswith("src/dataforge/dbt/"):
        return "dbt"
    if name.startswith("ui/"):
        return "Streamlit UI"
    if name.startswith("prompts/"):
        return "Prompts and response schemas"
    if name.startswith("scripts/docs/"):
        return "Documentation tooling"
    if name.startswith("scripts/build/"):
        return "Build and packaging tooling"
    if name.startswith("scripts/"):
        return "Verification and release tooling"
    if name.startswith(".github/"):
        return "Continuous integration and repository templates"
    if name in {"app.py", "src/dataforge/__init__.py", "src/dataforge/launcher.py",
                "src/dataforge/cli.py", "src/dataforge/build.py"}:
        return "Entry points and package"
    if name.startswith("src/dataforge/parsers/") or stem in {"models", "asset_identity", "schemas", "services"}:
        return "Static parsing and identity"
    if name.startswith("src/dataforge/"):
        if stem.startswith(("ai_", "llm", "focused_")) or stem in {
            "provider_service", "model_capabilities", "assistance_queue", "project_analysis", "analysis_service",
        } or "/tokenizer_assets/" in name:
            return "AI and provider services"
        if stem in {"graph", "transformations", "exports", "excel_exports", "reporting", "artifacts",
                    "graph_images", "graph_image_service", "image_worker"}:
            return "Graphs, columns and exports"
        return "Storage and configuration"
    return "Runtime and development configuration"


def python_details(path: Path, tests: bool = False) -> tuple[str, str]:
    """Extract documentation and declared names without importing or executing source."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    doc = ast.get_docstring(tree)
    summary = " ".join(doc.split()) if doc else "No module docstring; inspect the linked source."
    if len(summary) > 240:
        summary = summary[:237].rsplit(" ", 1)[0] + "…"
    declared = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_") and not (tests and node.name.startswith("test_")):
                declared.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    if target.id.isupper() or target.id in {"app", "mcp"}:
                        declared.append(target.id)
    symbols = ", ".join(f"`{name}`" for name in dict.fromkeys(declared)) or "—"
    if tests:
        count = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name.startswith("test_") for node in ast.walk(tree))
        symbols = f"{count} test functions" + (f"; helpers/constants: {symbols}" if declared else "")
    return summary, symbols


def resource_summary(name: str) -> str:
    """Describe resource types conservatively; source files remain the authority."""
    if name.startswith("prompts/"):
        return "Response schema (JSON)." if name.endswith(".json") else "Versioned prompt text or prompt authoring notes."
    if name.startswith("tests/"):
        return "Fixture input, expected result or sample archive; data for tests, never application code to execute."
    if name.startswith(".github/workflows/"):
        return "GitHub Actions workflow; inspect triggers, jobs and required commands."
    types = {
        ".toml": "TOML configuration or package/build metadata.",
        ".yaml": "YAML configuration.", ".yml": "YAML configuration or repository template.",
        ".ps1": "PowerShell build, installation or signing tooling.",
        ".iss": "Inno Setup Windows installer specification.",
        ".css": "UI stylesheet.", ".png": "UI image asset.",
        ".tiktoken": "Bundled tokenizer rank data for offline token accounting.",
        ".lock": "Resolved dependency lock; regenerate with the documented package manager.",
    }
    return types.get(Path(name).suffix, "Repository configuration, packaging input or resource; inspect source for exact values.")


def cell(value: str) -> str:
    """Escape source-derived table text without interpreting HTML or table separators."""
    return html.escape(value, quote=False).replace("|", "\\|")


def render_inventory(root: Path) -> str:
    """Render a deterministic inventory from the current checkout and pinned source tree."""
    baseline_paths = set(git_paths(root, "ls-tree", "-r", "--name-only", "-z", BASELINE))
    grouped: dict[str, list[str]] = defaultdict(list)
    paths = inventory_paths(root)
    for name in paths:
        grouped[subsystem(name)].append(name)
    lines = [
        "# First-party file inventory", "",
        "<!-- Generated by scripts/docs/inventory.py; edit source docstrings or the generator, then regenerate. -->", "",
        "Use this index to locate a file, then read the [development guide](index.md) for ownership and edit boundaries.",
        "Declared Python names below are internal developer APIs, not a supported public SDK. The list includes public",
        "top-level functions/classes, uppercase assignments and adapter `app`/`mcp` objects; it omits imported aliases",
        "and class methods. Test rows report syntactic test-function counts and declared helpers, not collected test-case counts.", "",
        f"Source links are pinned to baseline [`{BASELINE[:7]}`]({REPOSITORY}/tree/{BASELINE}).",
        "Files introduced by the documentation overhaul are labeled **new** until a published commit can be linked.",
        "Summaries come from module docstrings (trimmed to 240 characters) or resource types, so the linked implementation",
        "and focused tests remain the authority for exact behavior.", "",
        f"This inventory covers **{len(paths)} files**: all Git-tracked and nonignored additions under `src/`, `ui/`,",
        "`scripts/`, `tests/`, `prompts/`, `.github/` and `.streamlit/`, plus the explicitly listed root entry point,",
        "dependency, container and repository configuration files. It includes fixture inputs and sample archives.",
        "It excludes `KNOWLEDGE.md` context maps, documentation pages, planning/context folders, generated artifacts,",
        "caches, virtual environments, Git-ignored files and user data. Python source is parsed with `ast`; application",
        "modules and fixture code are never imported or executed.", "",
        "Regenerate from the checkout root:", "", "```sh", "python scripts/docs/inventory.py",
        "python scripts/docs/inventory.py --check", "```", "",
        "`--check` exits nonzero when file coverage, summaries or declared names have drifted. It never rewrites the page.", "",
        "## Subsystems", "", "| Subsystem | Files |", "| --- | ---: |",
    ]
    for group in GROUPS:
        if group in grouped:
            anchor = group.lower().replace(",", "").replace(":", "").replace(" ", "-")
            lines.append(f"| [{group}](#{anchor}) | {len(grouped[group])} |")
    for group in GROUPS:
        if group not in grouped:
            continue
        lines += ["", f"## {group}", "", "| File | Responsibility / module summary | Declared names / checks |", "| --- | --- | --- |"]
        for name in grouped[group]:
            link = (f"[`{name}`]({REPOSITORY}/blob/{BASELINE}/{name})" if name in baseline_paths
                    else f"`{name}` **new**")
            if name.endswith(".py"):
                summary, symbols = python_details(root / name, name.startswith("tests/"))
            else:
                summary, symbols = resource_summary(name), "—"
            lines.append(f"| {link} | {cell(summary)} | {cell(symbols)} |")
    return "\n".join(lines) + "\n"


def write_inventory(root: Path, output: Path, check: bool = False) -> bool:
    """Write the generated page, or return whether the saved page matches in check mode."""
    content = render_inventory(root)
    if check:
        return output.is_file() and output.read_text(encoding="utf-8") == content
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    """Generate the developer inventory or check its freshness."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the saved inventory is stale")
    args = parser.parse_args()
    if not write_inventory(ROOT, ROOT / OUTPUT, args.check):
        print(f"Stale inventory: run python scripts/docs/inventory.py to update {OUTPUT}")
        return 1
    print(f"{'Checked' if args.check else 'Generated'} {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
