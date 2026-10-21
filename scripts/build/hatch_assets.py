"""Allowlist packaged UI/resources; directory force-includes bypass Hatch exclusions."""
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class AssetsHook(BuildHookInterface):
    """Include the application UI and prompt resources in built packages."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Populate Hatch's force-include mapping with approved application assets.

        Args:
            version: Version string for the build being created.
            build_data: Mutable Hatch build metadata to update with asset paths.
        """
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
