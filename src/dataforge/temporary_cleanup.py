"""Cleanup only stale app-created recovery staging files; journal bytes before removal."""
import gzip
import hashlib
import io
import os
import re
import stat
import time
import uuid
from pathlib import Path
from typing import Any

from dataforge.maintenance import MAX_ARCHIVE_BYTES, _idle
from dataforge.maintenance import _directory as _history_directory
from dataforge.store import Store

NAME = re.compile(r"[0-9a-f]{32}\.tmp")


def _directory(store: Store, workspace: str) -> Path:
    """Resolve and validate the workspace-owned temporary recovery directory."""
    resolved = _history_directory(store, workspace)
    expected = store.home / "history-recovery" / workspace
    if resolved != expected:
        raise ValueError("Temporary recovery directory cannot redirect to another location")
    for path in (expected.parent, expected):
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Temporary recovery directory cannot be a symlink or reparse point")
    return expected


def _identity(info: os.stat_result) -> dict[str, int]:
    """Return stable filesystem identity fields used to detect file replacement."""
    return {"size": info.st_size, "modified_ns": info.st_mtime_ns, "device": info.st_dev, "inode": info.st_ino}


def _regular(info: os.stat_result) -> bool:
    """Check that a filesystem entry is a single-link, non-reparse regular file."""
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not getattr(info, "st_file_attributes", 0) & 0x400


def _plan(store: Store, workspace: str, age_hours: int) -> dict[str, Any]:
    """Build a bounded, identity-pinned preview of old eligible recovery files."""
    if type(age_hours) is not int or not 24 <= age_hours <= 8760:
        raise ValueError("Temporary files must be at least 24 hours old; maximum age setting is one year")
    directory = _directory(store, workspace)
    files, total, truncated = [], 0, False
    if not directory.exists():
        return {"files": files, "bytes": total, "truncated": False}
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= 10000:
                truncated = True
                break
            if not NAME.fullmatch(entry.name):
                continue
            # Windows DirEntry cached stat omits link count/inode; lstat supplies identity.
            info = (directory / entry.name).lstat()
            if not _regular(info) or info.st_mtime > time.time() - age_hours * 3600:
                continue
            if len(files) >= 100 or total + info.st_size > MAX_ARCHIVE_BYTES:
                truncated = True
                continue
            files.append({"name": entry.name, **_identity(info)})
            total += info.st_size
    return {"files": sorted(files, key=lambda row: row["name"]), "bytes": total, "truncated": truncated}


def temporary_plan(store: Store, workspace: str, age_hours: int = 24) -> dict[str, Any]:
    """Return a preview of eligible temporary recovery files without deleting them."""
    with _idle(store):
        return _plan(store, workspace, age_hours)


def cleanup_temporary(store: Store, workspace: str, preview: list[dict[str, Any]], age_hours: int = 24) -> dict[str, Any]:
    """Journal selected temporary files before removing them from the recovery directory.

    Args:
        store: Workspace store holding recovery records.
        workspace: Workspace identifier owning the files.
        preview: Selected file identities from a prior temporary plan.
        age_hours: Minimum file age required for cleanup.

    Returns:
        Count of removed files and their recovery record IDs.

    Raises:
        ValueError: If the preview is invalid or a file changes during validation.
    """
    if not isinstance(preview, list) or not 1 <= len(preview) <= 100:
        raise ValueError("Select between 1 and 100 previewed temporary files")
    with _idle(store):
        current = {row["name"]: row for row in _plan(store, workspace, age_hours)["files"]}
        names = []
        for row in preview:
            if not isinstance(row, dict) or row.get("name") not in current or row != current[row["name"]]:
                raise ValueError("Temporary file changed or is ineligible; refresh the preview")
            names.append(row["name"])
        if len(set(names)) != len(names):
            raise ValueError("Select each temporary file only once")
        recovery_ids = []
        for row in preview:
            path = _directory(store, workspace) / row["name"]
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not _regular(info) or _identity(info) != {k: row[k] for k in _identity(info)}:
                    raise ValueError("Temporary file changed; refresh the preview")
                body = stream.read(MAX_ARCHIVE_BYTES + 1)
                if len(body) != row["size"] or _identity(os.fstat(stream.fileno())) != _identity(info):
                    raise ValueError("Temporary file changed while reading; nothing was removed")
            rid = uuid.uuid4().hex
            with store.transaction():
                store.execute("INSERT INTO temporary_recovery(recovery_id,workspace_id,file_name,recovery_body,byte_count,sha256) VALUES (?,?,?,?,?,?)",
                              [rid, workspace, row["name"], gzip.compress(body, mtime=0), len(body), hashlib.sha256(body).hexdigest()])
            # A committed recovery copy exists even if final revalidation/removal fails.
            _directory(store, workspace)
            final = path.lstat()
            if not _regular(final) or _identity(final) != _identity(info):
                raise ValueError("Temporary file changed after recovery; original retained")
            path.unlink()
            recovery_ids.append(rid)
        return {"removed": len(recovery_ids), "recovery_ids": recovery_ids}


def temporary_recoveries(store: Store, workspace: str) -> list[dict[str, Any]]:
    """List the latest recovery records for temporary files in a workspace."""
    _directory(store, workspace)
    return store.rows("SELECT recovery_id,file_name,byte_count,created_at,restored_at FROM temporary_recovery WHERE workspace_id=? ORDER BY created_at DESC LIMIT 100", [workspace])


def restore_temporary(store: Store, workspace: str, recovery_id: str) -> dict[str, Any]:
    """Restore a journaled temporary file without overwriting an existing path."""
    if not isinstance(recovery_id, str) or not re.fullmatch(r"[0-9a-f]{32}", recovery_id):
        raise ValueError("Invalid temporary recovery identity")
    with _idle(store):
        rows = store.rows("SELECT * FROM temporary_recovery WHERE workspace_id=? AND recovery_id=?", [workspace, recovery_id])
        if not rows or not NAME.fullmatch(rows[0]["file_name"]):
            raise ValueError("Temporary recovery does not belong to this workspace")
        row = rows[0]
        with gzip.GzipFile(fileobj=io.BytesIO(row["recovery_body"])) as stream:
            body = stream.read(MAX_ARCHIVE_BYTES + 1)
        if len(body) != row["byte_count"] or len(body) > MAX_ARCHIVE_BYTES or hashlib.sha256(body).hexdigest() != row["sha256"]:
            raise ValueError("Temporary recovery integrity validation failed")
        directory = _directory(store, workspace)
        directory.mkdir(parents=True, exist_ok=True)
        _directory(store, workspace)
        path = directory / row["file_name"]
        if path.exists() or path.is_symlink():
            raise ValueError("Temporary file already exists; restore will not overwrite it")
        temporary = directory / (uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            _directory(store, workspace)
            # Atomic create-if-absent publication: replacement must never overwrite a new file.
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        store.execute("UPDATE temporary_recovery SET restored_at=current_timestamp WHERE workspace_id=? AND recovery_id=?", [workspace, recovery_id])
        return {"restored": row["file_name"], "bytes": len(body)}
