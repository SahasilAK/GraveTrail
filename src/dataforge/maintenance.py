"""Bounded, recoverable history maintenance. Current facts and source bytes are untouched."""
import gzip
import hashlib
import io
import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

TABLES = {
    "analysis_runs": ("run_id", "workspace_id", "status", "analyzed", "cached", "duration",
                      "configuration", "snapshot", "error", "created_at"),
    "ingestion_runs": ("ingestion_id", "workspace_id", "source", "report", "created_at"),
}
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024


def _directory(store, workspace):
    if not isinstance(workspace, str) or not re.fullmatch(r"[0-9a-f]{32}", workspace):
        raise ValueError("Invalid workspace identity")
    if not store.rows("SELECT 1 FROM workspaces WHERE workspace_id=?", [workspace]):
        raise ValueError("Workspace does not exist")
    directory = (store.home / "history-recovery" / workspace).resolve()
    if not directory.is_relative_to(store.home):
        raise ValueError("History recovery location must stay inside the data home")
    return directory


@contextmanager
def _idle(store):
    if not store.analysis_lock.acquire(blocking=False):
        raise ValueError("Analysis is running; retry history maintenance after it finishes")
    try:
        with store.lock:
            from dataforge.cleanup import assert_idle
            from dataforge.llm_resources import block_requests_for_maintenance
            with block_requests_for_maintenance(store.home):
                assert_idle(store)
                yield
    finally:
        store.analysis_lock.release()


def history_plan(store, workspace, keep_runs=20, keep_imports=20, batch_size=25):
    _directory(store, workspace)
    if any(type(v) is not int or not 1 <= v <= 10000 for v in (keep_runs, keep_imports)):
        raise ValueError("Keep between 1 and 10,000 history records")
    if type(batch_size) is not int or not 1 <= batch_size <= 100:
        raise ValueError("Use a cleanup batch of 1–100 records per type")
    runs = store.rows("""SELECT run_id FROM (
        SELECT run_id,row_number() OVER (ORDER BY created_at DESC,run_id DESC) AS ordinal
        FROM analysis_runs WHERE workspace_id=? AND status IN ('completed','failed','cancelled')) r
        WHERE ordinal>? AND NOT EXISTS (
            SELECT 1 FROM edges e WHERE e.workspace_id=? AND e.run_id=r.run_id)
        AND run_id NOT IN (SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed'
            ORDER BY created_at DESC,run_id DESC LIMIT 1)
        ORDER BY ordinal DESC LIMIT ?""", [workspace, keep_runs, workspace, workspace, batch_size])
    imports = store.rows("""SELECT ingestion_id FROM (
        SELECT ingestion_id,row_number() OVER (ORDER BY created_at DESC,ingestion_id DESC) AS ordinal
        FROM ingestion_runs WHERE workspace_id=?) r WHERE ordinal>? AND NOT EXISTS (
            SELECT 1 FROM source_files f WHERE f.workspace_id=? AND f.ingestion_id=r.ingestion_id)
        ORDER BY ordinal DESC LIMIT ?""", [workspace, keep_imports, workspace, batch_size])
    return {"analysis_runs": [r["run_id"] for r in runs], "ingestion_runs": [r["ingestion_id"] for r in imports]}


def _canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode("utf-8")


def archive_history(store, workspace, keep_runs=20, keep_imports=20, batch_size=25):
    with _idle(store):
        plan = history_plan(store, workspace, keep_runs, keep_imports, batch_size)
        if not any(plan.values()):
            raise ValueError("No unreferenced history records meet these limits")
        records = {}
        for table, ids in plan.items():
            records[table] = []
            if not ids:
                continue
            placeholders = ",".join("?" for _ in ids)
            text_fields = ("configuration", "snapshot", "error") if table == "analysis_runs" else ("source", "report")
            measure = "+".join(f"length(coalesce({field},''))" for field in text_fields)
            size = store.rows(f"SELECT coalesce(sum({measure}),0) AS size FROM {table} WHERE workspace_id=? AND {TABLES[table][0]} IN ({placeholders})", [workspace, *ids])[0]["size"]
            if size * 6 > MAX_ARCHIVE_BYTES - 4096:
                raise ValueError("History payload exceeds recovery budget; reduce the batch size")
            records[table] = store.rows(f"SELECT {','.join(TABLES[table])} FROM {table} WHERE workspace_id=? AND {TABLES[table][0]} IN ({placeholders})", [workspace, *ids])
        payload = {"format": "dataforge-history-v1", "workspace_id": workspace, "records": records}
        body = _canonical({"payload": payload, "sha256": hashlib.sha256(_canonical(payload)).hexdigest()})
        if len(body) > MAX_ARCHIVE_BYTES:
            raise ValueError("History archive exceeds 25 MB; reduce the batch size")
        directory = _directory(store, workspace)
        directory.mkdir(parents=True, exist_ok=True)
        archive_id = uuid.uuid4().hex
        temporary, target = directory / (archive_id + ".tmp"), directory / (archive_id + ".json")
        # Both absolute paths are inside the checked recovery directory; no user paths are moved.
        with temporary.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
        # Journal and removal commit together; recovery does not depend on directory fsync support.
        # A failed transaction preserves all records and leaves the extra recovery file available.
        with store.transaction():
            store.execute("INSERT INTO history_archives(archive_id,workspace_id,recovery_body,archive_bytes) VALUES (?,?,?,?)",
                          [archive_id, workspace, gzip.compress(body, compresslevel=6, mtime=0), len(body)])
            for table, ids in plan.items():
                if ids:
                    store.execute(f"DELETE FROM {table} WHERE workspace_id=? AND {TABLES[table][0]} IN ({','.join('?' for _ in ids)})", [workspace, *ids])
        return {"archive_id": archive_id, **{table: len(rows) for table, rows in records.items()}}


def list_archives(store, workspace):
    directory = _directory(store, workspace)
    paths = [p for p in directory.glob("*.json")
             if re.fullmatch(r"[0-9a-f]{32}", p.stem) and p.is_file() and not p.is_symlink()]
    items = {r["archive_id"]: {"archive_id": r["archive_id"], "bytes": r["archive_bytes"],
        "created_at": r["created_at"].replace(tzinfo=timezone.utc).isoformat(), "recovery": "database + file"}
        for r in store.rows("SELECT archive_id,archive_bytes,created_at FROM history_archives WHERE workspace_id=? ORDER BY created_at DESC LIMIT 100", [workspace])}
    for item in items.values():
        if not (directory / (item["archive_id"] + ".json")).is_file():
            item["recovery"] = "database"
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
        items.setdefault(path.stem, {"archive_id": path.stem, "bytes": path.stat().st_size,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(), "recovery": "file"})
    return sorted(items.values(), key=lambda a: a["created_at"], reverse=True)[:100]


def restore_history(store, workspace, archive_id):
    if not isinstance(archive_id, str) or not re.fullmatch(r"[0-9a-f]{32}", archive_id):
        raise ValueError("Invalid recovery archive identity")
    with _idle(store):
        path = _directory(store, workspace) / (archive_id + ".json")
        if path.is_symlink():
            raise ValueError("Recovery archives cannot be symlinks")
        backups = store.rows("SELECT recovery_body FROM history_archives WHERE workspace_id=? AND archive_id=?", [workspace, archive_id])
        if backups:
            with gzip.GzipFile(fileobj=io.BytesIO(backups[0]["recovery_body"])) as stream:
                data = stream.read(MAX_ARCHIVE_BYTES + 1)
        elif path.is_file():
            with path.open("rb") as stream:
                data = stream.read(MAX_ARCHIVE_BYTES + 1)
        else:
            raise ValueError("History recovery archive not found")
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("History archive exceeds 25 MB")
        try:
            envelope = json.loads(data)
            payload = envelope["payload"]
            if envelope["sha256"] != hashlib.sha256(_canonical(payload)).hexdigest():
                raise ValueError("History archive integrity check failed")
            if payload["format"] != "dataforge-history-v1" or payload["workspace_id"] != workspace:
                raise ValueError("History archive does not belong to this workspace")
            records = payload["records"]
            if set(records) != set(TABLES):
                raise ValueError("Unsupported history tables")
            for table, rows in records.items():
                if not isinstance(rows, list) or len(rows) > 100:
                    raise ValueError("Invalid history record count")
                for row in rows:
                    if (not isinstance(row, dict) or set(row) != set(TABLES[table])
                            or row["workspace_id"] != workspace
                            or not isinstance(row[TABLES[table][0]], str)
                            or not re.fullmatch(r"[0-9a-f]{32}", row[TABLES[table][0]])
                            or any(not isinstance(v, (str, int, float, type(None))) for v in row.values())):
                        raise ValueError("Invalid history record")
                    if table == "analysis_runs" and row["status"] not in {"completed", "failed", "cancelled"}:
                        raise ValueError("Running analyses cannot be restored")
        except (KeyError, TypeError, RecursionError, UnicodeError) as exc:
            raise ValueError("Invalid history archive") from exc
        restored = {table: 0 for table in TABLES}
        with store.transaction():
            for table, rows in records.items():
                columns = TABLES[table]
                for row in rows:
                    if not store.rows(f"SELECT 1 FROM {table} WHERE {columns[0]}=?", [row[columns[0]]]):
                        store.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                                      [row[c] for c in columns])
                        restored[table] += 1
        return restored
