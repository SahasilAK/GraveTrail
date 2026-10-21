"""Allowlist packaged UI/resources; directory force-includes bypass Hatch exclusions."""
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class AssetsHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        files = {"app.py": "dataforge/_app/app.py",
                 "dependency-overrides.txt": "dataforge/dependency-overrides.txt",
                 ".streamlit/config.toml": "dataforge/_app/.streamlit/config.toml"}
        for folder, extensions, destination in (("ui", {".py", ".css", ".png"}, "dataforge/_app/ui"),
                                                 ("prompts", {".md", ".json"}, "dataforge/prompts")):
            for path in (root / folder).rglob("*"):
                if path.is_file() and path.suffix in extensions and not path.is_symlink():
                    relative = path.relative_to(root / folder).as_posix()
                    files[path.relative_to(root).as_posix()] = f"{destination}/{relative}"
        build_data["force_include"].update(files)
