import json
from pathlib import Path
from typing import Any

import pytest

from dataforge.ingestion import Importer
from dataforge.services import analyze
from dataforge.store import Store


def populated(store: Any, name: str) -> Any:
    """Handle populated for the test scenario.

    Args:
        store: Store instance exercised by the test.
        name: Name value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    w = store.create_workspace(name)
    importer = Importer(store, w)
    for i in range(4):
        importer.files([("q.sql", f"CREATE TABLE mart.x AS SELECT id FROM raw.a WHERE id>{i};".encode())], {".sql"})
        analyze(store, w)
    return w


def test_archive_restore_preserves_active_facts_and_isolates_workspaces(tmp_path: Path) -> None:
    """Verify that archive restore preserves active facts and isolates workspaces.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.maintenance import archive_history, history_plan, list_archives, restore_history

    store = Store(tmp_path)
    try:
        w, other = populated(store, "One"), populated(store, "Other")
        edges = store.edges(w)
        files = store.files(w)
        originals = store.original(files[0]["file_id"])
        plan = history_plan(store, w, keep_runs=1, keep_imports=1)
        assert len(plan["analysis_runs"]) == len(plan["ingestion_runs"]) == 3
        archived = archive_history(store, w, keep_runs=1, keep_imports=1)
        assert archived["analysis_runs"] == archived["ingestion_runs"] == 3
        assert len(store.runs(w)) == 1 and len(store.runs(other)) == 4
        assert store.edges(w) == edges and store.files(w) == files
        assert store.original(files[0]["file_id"]) == originals
        assert len(list_archives(store, w)) == 1 and list_archives(store, other) == []
        restored = restore_history(store, w, archived["archive_id"])
        assert restored == {"analysis_runs": 3, "ingestion_runs": 3}
        assert restore_history(store, w, archived["archive_id"]) == {"analysis_runs": 0, "ingestion_runs": 0}
        assert len(store.runs(w)) == 4 and store.edges(w) == edges
    finally:
        store.close()


def test_archive_failure_rolls_back_metadata_and_leaves_recovery_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that archive failure rolls back metadata and leaves recovery file.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        RuntimeError: Raised by the test helper.
    """
    from dataforge.maintenance import archive_history, list_archives

    store = Store(tmp_path)
    try:
        w = populated(store, "Rollback")
        execute = store.execute
        def fail_delete(sql: str, params: Any=None) -> Any:
            """Handle fail delete for the test scenario.

            Args:
                sql: SQL source text for the test case.
                params: Params value used by the test case.

            Returns:
                Value produced for the test scenario.

            Raises:
                RuntimeError: Raised by the test helper.
            """
            if sql.startswith("DELETE FROM ingestion_runs"):
                raise RuntimeError("Injected failure")
            return execute(sql, params)
        monkeypatch.setattr(store, "execute", fail_delete)
        with pytest.raises(RuntimeError, match="Injected"):
            archive_history(store, w, keep_runs=1, keep_imports=1)
        assert len(store.runs(w)) == 4
        assert len(store.rows("SELECT * FROM ingestion_runs WHERE workspace_id=?", [w])) == 4
        assert len(list_archives(store, w)) == 1
        assert store.rows("SELECT * FROM history_archives") == []
    finally:
        store.close()


def test_recovery_survives_restart_and_rejects_tampering_and_cross_workspace(tmp_path: Path) -> None:
    """Verify that recovery survives restart and rejects tampering and cross workspace.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.maintenance import archive_history, restore_history

    store = Store(tmp_path)
    w = populated(store, "Recovery")
    other = store.create_workspace("Other")
    result = archive_history(store, w, keep_runs=1, keep_imports=1)
    store.close()
    store = Store(tmp_path)
    try:
        with pytest.raises((ValueError, OSError)):
            restore_history(store, other, result["archive_id"])
        with pytest.raises(ValueError):
            restore_history(store, w, "../outside")
        assert restore_history(store, w, result["archive_id"])["analysis_runs"] == 3
        path = tmp_path / "history-recovery" / w / (result["archive_id"] + ".json")
        obj = json.loads(path.read_text())
        obj["payload"]["workspace_id"] = other
        path.write_text(json.dumps(obj))
        assert restore_history(store, w, result["archive_id"])["analysis_runs"] == 0
        store.execute("DELETE FROM history_archives WHERE archive_id=?", [result["archive_id"]])
        with pytest.raises(ValueError):
            restore_history(store, w, result["archive_id"])
    finally:
        store.close()


def test_maintenance_rejects_running_analysis_and_preserves_latest_completed(tmp_path: Path) -> None:
    """Verify that maintenance rejects running analysis and preserves latest completed.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.maintenance import archive_history, history_plan

    store = Store(tmp_path)
    try:
        w = populated(store, "Running")
        store.analysis_lock.acquire()
        try:
            with pytest.raises(ValueError, match="running"):
                archive_history(store, w, keep_runs=1, keep_imports=1)
        finally:
            store.analysis_lock.release()
        latest = store.runs(w)[0]["run_id"]
        store.execute("INSERT INTO analysis_runs(run_id,workspace_id,status) VALUES (?,?,?)", ["f" * 32, w, "failed"])
        plan = history_plan(store, w, keep_runs=1, keep_imports=1)
        assert latest not in plan["analysis_runs"]
        with pytest.raises(ValueError):
            history_plan(store, w, keep_runs=0, keep_imports=1)
    finally:
        store.close()


def test_active_inventory_import_records_are_protected_and_batches_are_bounded(tmp_path: Path) -> None:
    """Verify that active inventory import records are protected and batches are bounded.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.maintenance import history_plan

    store = Store(tmp_path)
    try:
        w = populated(store, "Batch")
        plan = history_plan(store, w, keep_runs=1, keep_imports=1, batch_size=1)
        assert len(plan["analysis_runs"]) == len(plan["ingestion_runs"]) == 1
        other = store.create_workspace("Referenced imports")
        for i in range(3):
            Importer(store, other).files([(f"{i}.sql", b"SELECT id FROM raw.a;")], {".sql"})
        assert history_plan(store, other, keep_imports=1)["ingestion_runs"] == []
    finally:
        store.close()


def test_failed_restore_has_no_partial_database_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that failed restore has no partial database changes.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        RuntimeError: Raised by the test helper.
    """
    from dataforge.maintenance import archive_history, restore_history

    store = Store(tmp_path)
    try:
        w = populated(store, "Atomic recovery")
        archived = archive_history(store, w, keep_runs=1, keep_imports=1)
        execute, calls = store.execute, []
        def fail_second_insert(sql: str, params: Any=None) -> Any:
            """Handle fail second insert for the test scenario.

            Args:
                sql: SQL source text for the test case.
                params: Params value used by the test case.

            Returns:
                Value produced for the test scenario.

            Raises:
                RuntimeError: Raised by the test helper.
            """
            if sql.startswith("INSERT INTO analysis_runs"):
                calls.append(1)
                if len(calls) == 2:
                    raise RuntimeError("Injected restore failure")
            return execute(sql, params)
        monkeypatch.setattr(store, "execute", fail_second_insert)
        with pytest.raises(RuntimeError, match="restore"):
            restore_history(store, w, archived["archive_id"])
        assert len(store.runs(w)) == 1
        assert len(store.rows("SELECT * FROM ingestion_runs WHERE workspace_id=?", [w])) == 1
    finally:
        store.close()


def test_history_size_budget_is_checked_before_removal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that history size budget is checked before removal.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    import dataforge.maintenance as maintenance

    store = Store(tmp_path)
    try:
        w = populated(store, "Budget")
        monkeypatch.setattr(maintenance, "MAX_ARCHIVE_BYTES", 1000)
        with pytest.raises(ValueError, match="budget|MB"):
            maintenance.archive_history(store, w, keep_runs=1, keep_imports=1)
        assert len(store.runs(w)) == 4
    finally:
        store.close()


def test_database_recovery_survives_missing_archive_file_and_restart(tmp_path: Path) -> None:
    """Verify that database recovery survives missing archive file and restart.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.maintenance import archive_history, list_archives, restore_history

    store = Store(tmp_path)
    w = populated(store, "Durable recovery")
    result = archive_history(store, w, keep_runs=1, keep_imports=1)
    # Simulate loss of the filesystem publication; original rows were already archived.
    (tmp_path / "history-recovery" / w / (result["archive_id"] + ".json")).unlink()
    store.close()
    store = Store(tmp_path)
    try:
        assert list_archives(store, w)[0]["archive_id"] == result["archive_id"]
        assert restore_history(store, w, result["archive_id"]) == {"analysis_runs": 3, "ingestion_runs": 3}
        assert len(store.runs(w)) == 4
    finally:
        store.close()


def test_history_journal_migration_preserves_v2_facts(tmp_path: Path) -> None:
    """Verify that history journal migration preserves v2 facts.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    w = populated(store, "Migration")
    edges = store.edges(w)
    store.execute("DROP TABLE IF EXISTS history_archives")
    store.execute("DELETE FROM schema_migrations WHERE version=3")
    store.close()
    upgraded = Store(tmp_path)
    try:
        assert (3 in {r["version"] for r in upgraded.rows("SELECT version FROM schema_migrations")})
        assert upgraded.edges(w) == edges and len(upgraded.runs(w)) == 4
        assert upgraded.rows("SELECT * FROM history_archives") == []
    finally:
        upgraded.close()
