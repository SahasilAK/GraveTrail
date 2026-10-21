"""Explicit startup-approved storage homes; selecting never copies or moves data."""
import os
from pathlib import Path


def allowed_homes(default_home: str | Path, configured: str = "") -> list[str]:
    """Resolve the default and configured storage homes into a bounded allowlist.

    Args:
        default_home: Default storage directory.
        configured: Optional path-separated list of additional absolute directories.

    Returns:
        Unique resolved storage paths, with the default path first.

    Raises:
        ValueError: If a configured path is relative or more than eight homes are supplied.
    """
    homes = [str(Path(default_home).expanduser().resolve())]
    for value in configured.split(os.pathsep):
        if not value.strip():
            continue
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            raise ValueError("DATAFORGE_STORAGE_LOCATIONS requires absolute directory paths")
        home = str(path.resolve())
        if home not in homes:
            homes.append(home)
        if len(homes) > 8:
            raise ValueError("Configure at most eight storage locations including DATAFORGE_HOME")
    return homes


def validate_home(value: str | Path, homes: list[str]) -> str:
    """Resolve a selected storage home and require it to be startup-approved.

    Args:
        value: Selected storage directory.
        homes: Resolved allowlist produced during startup.

    Returns:
        The selected directory's resolved path.

    Raises:
        ValueError: If the resolved path is not present in the allowlist.
    """
    resolved = str(Path(value).expanduser().resolve())
    if resolved not in homes:
        raise ValueError("Storage location is not in the startup allowlist")
    return resolved
