"""Explicit publication boundary: nav documents and named assets only."""
from pathlib import Path, PurePosixPath


def on_config(config):
    # Docs-only builds load the shared definitions without installing the app dependencies.
    from runpy import run_path

    themes = run_path(str(Path(__file__).resolve().parents[2] / "src/dataforge/theme_configuration.py"))
    config.extra["palette_css"] = themes["site_theme_css"]()
    config.theme["palette"] = [
        {"scheme": scheme, "primary": "custom", "accent": "custom",
         "toggle": {"icon": "material/palette-outline", "name": name}}
        for scheme, name in sorted(themes["SITE_THEMES"].items(), key=lambda item: item[0] != "obsidian-ember")]
    return config


def nav_documents(nav):
    for entry in nav:
        if isinstance(entry, dict):
            for value in entry.values():
                if isinstance(value, list):
                    yield from nav_documents(value)
                elif isinstance(value, str) and value.endswith(".md"):
                    yield value
        elif isinstance(entry, str) and entry.endswith(".md"):
            yield entry


def page_output(name: str) -> str:
    path = PurePosixPath(name).with_suffix("").as_posix().lower()
    return path + ".html" if path.endswith("index") else path + "/index.html"


def public_files(root: Path, names: set[str]) -> set[str]:
    for name in names:
        path = PurePosixPath(name)
        if (
            path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
            or path.suffix not in {".md", ".svg", ".png", ".jpg", ".webp", ".css", ".js"}
            or any(part.startswith(".") for part in path.parts)
            or path.name == "KNOWLEDGE.md"
            or any(part in {"prompts", "plans"} for part in path.parts)
        ):
            raise ValueError(f"Unsafe publication path: {name}")
        target = root / name
        if any(part.is_symlink() for part in (target, *target.parents)):
            raise ValueError(f"Unsafe symlink in publication path: {name}")
        if not target.is_file():
            raise ValueError(f"Publication source missing: {name}")
    return names


def on_files(files, config):
    import material
    from mkdocs.structure.files import Files

    allowed = public_files(
        Path(config.docs_dir),
        set(nav_documents(config.nav)) | set(config.extra["public_assets"]),
    )
    # Lowercase output avoids ARCHITECTURE.md colliding with architecture/ on Windows.
    for file in files:
        if file.src_uri in allowed and file.is_documentation_page():
            file.dest_uri = page_output(file.src_uri)
            file.__dict__.pop("url", None)
            file.__dict__.pop("abs_dest_path", None)
    theme = Path(material.__file__).resolve().parent / "templates"
    return Files(
        file for file in files
        if file.src_uri in allowed or Path(file.abs_src_path).resolve().is_relative_to(theme)
    )
