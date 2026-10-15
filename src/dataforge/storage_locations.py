"""Explicit startup-approved storage homes; selecting never copies or moves data."""
import os
from pathlib import Path


def allowed_homes(default_home, configured=""):
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


def validate_home(value, homes):
    resolved = str(Path(value).expanduser().resolve())
    if resolved not in homes:
        raise ValueError("Storage location is not in the startup allowlist")
    return resolved
