import os
import time
from pathlib import Path
from typing import Any

import pytest

from dataforge.store import Store


def orphan(store: Any, workspace: Any, name: str="a" * 32 + ".tmp", body: str=b"unfinished recovery copy", age: Any=90000) -> Any:
    """Handle orphan for the test scenario.

    Args:
        store: Store instance exercised by the test.
        workspace: Workspace used by the test.
        name: Name value used by the test case.
        body: Body value used by the test case.
        age: Age value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    directory = store.home / "history-recovery" / workspace
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(body)
    os.utime(path, (time.time() - age, time.time() - age))
    return path


def test_cleanup_is_bounded_workspace_owned_and_recoverable_after_restart(tmp_path: Path) -> None:
    """Verify that cleanup is bounded workspace owned and recoverable after restart.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.temporary_cleanup import cleanup_temporary, restore_temporary, temporary_plan

    store = Store(tmp_path)
    w, other = store.create_workspace("One"), store.create_workspace("Other")
    old = orphan(store, w)
    body = old.read_bytes()
    fresh = orphan(store, w, "b" * 32 + ".tmp", age=0)
    archive = orphan(store, w, "c" * 32 + ".json")
    unknown = orphan(store, w, "user-notes.tmp")
    other_file = orphan(store, other)
    plan = temporary_plan(store, w)
    assert [r["name"] for r in plan["files"]] == [old.name]
    result = cleanup_temporary(store, w, plan["files"])
    assert result["removed"] == 1 and not old.exists()
    assert all(p.exists() for p in [fresh, archive, unknown, other_file])
    rid = result["recovery_ids"][0]
    store.close()
    store = Store(tmp_path)
    try:
        with pytest.raises(ValueError):
            restore_temporary(store, other, rid)
        restore_temporary(store, w, rid)
        assert old.read_bytes() == body
        with pytest.raises(ValueError, match="exists"):
            restore_temporary(store, w, rid)
        assert not temporary_plan(store, w)["files"]  # restored copy is fresh
    finally:
        store.close()


def test_changed_preview_and_failed_journal_do_not_remove_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that changed preview and failed journal do not remove files.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        RuntimeError: Raised by the test helper.
    """
    from dataforge.temporary_cleanup import cleanup_temporary, temporary_plan

    store = Store(tmp_path)
    w = store.create_workspace("Changed preview")
    path = orphan(store, w)
    plan = temporary_plan(store, w)
    path.write_bytes(b"new content")
    with pytest.raises(ValueError, match="changed"):
        cleanup_temporary(store, w, plan["files"])
    path = orphan(store, w)
    plan = temporary_plan(store, w)
    execute = store.execute

    def fail(sql: str, params: Any=None) -> Any:
        """Raise the injected failure used by the test.

        Args:
            sql: SQL source text for the test case.
            params: Params value used by the test case.

        Returns:
            Value produced for the test scenario.

        Raises:
            RuntimeError: Raised by the test helper.
        """
        if sql.startswith("INSERT INTO temporary_recovery"):
            raise RuntimeError("Injected journal failure")
        return execute(sql, params)

    monkeypatch.setattr(store, "execute", fail)
    with pytest.raises(RuntimeError):
        cleanup_temporary(store, w, plan["files"])
    assert path.exists()
    assert not store.rows("SELECT * FROM temporary_recovery")
    store.close()


def test_cleanup_refuses_active_analysis_and_untrusted_names(tmp_path: Path) -> None:
    """Verify that cleanup refuses active analysis and untrusted names.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.temporary_cleanup import cleanup_temporary, temporary_plan

    store = Store(tmp_path)
    w = store.create_workspace("Guarded")
    orphan(store, w)
    with pytest.raises(ValueError):
        cleanup_temporary(store, w, [{"name": "../../dataforge.duckdb"}])
    store.analysis_lock.acquire()
    try:
        with pytest.raises(ValueError, match="running"):
            temporary_plan(store, w)
    finally:
        store.analysis_lock.release()
        store.close()


def test_preview_bounds(tmp_path: Path) -> None:
    """Verify that preview bounds.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.temporary_cleanup import temporary_plan

    store = Store(tmp_path)
    w = store.create_workspace("Bounds")
    for i in range(102):
        orphan(store, w, f"{i:032x}.tmp")
    plan = temporary_plan(store, w)
    assert len(plan["files"]) == 100 and plan["truncated"]
    store.close()


def test_symlink_swap_keeps_external_file(tmp_path: Path) -> None:
    """Verify that symlink swap keeps external file.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.temporary_cleanup import cleanup_temporary, temporary_plan

    store = Store(tmp_path)
    w = store.create_workspace("Bounds")
    orphan(store, w)
    plan = temporary_plan(store, w)
    target = Path(tmp_path) / "protected"
    target.write_bytes(b"source")
    candidate = store.home / "history-recovery" / w / plan["files"][0]["name"]
    candidate.unlink()
    try:
        candidate.symlink_to(target)
    except OSError:
        store.close()
        pytest.skip("Windows symlink creation privilege unavailable")
    with pytest.raises(ValueError):
        cleanup_temporary(store, w, plan["files"][:1])
    assert target.read_bytes() == b"source"
    store.close()


def test_v3_upgrade_preserves_existing_inventory(tmp_path: Path) -> None:
    """Verify that v3 upgrade preserves existing inventory.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.ingestion import Importer

    store = Store(tmp_path)
    w = store.create_workspace("Migration preservation")
    Importer(store, w).files([("q.sql", b"select id from raw.a;")], {".sql"})
    store.execute("DROP TABLE temporary_recovery")
    store.execute("DELETE FROM schema_migrations WHERE version=4")
    store.close()
    reopened = Store(tmp_path)
    try:
        assert reopened.original(reopened.files(w)[0]["file_id"]) == b"select id from raw.a;"
        assert reopened.rows("SELECT version FROM schema_migrations WHERE version=4")
        assert reopened.rows("SELECT * FROM temporary_recovery") == []
    finally:
        reopened.close()


def test_restore_publication_failure_leaves_recovery_and_no_partial_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that restore publication failure leaves recovery and no partial target.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        OSError: Raised by the test helper.
    """
    from dataforge.temporary_cleanup import cleanup_temporary, restore_temporary, temporary_plan

    store = Store(tmp_path)
    w = store.create_workspace("Atomic restore")
    path = orphan(store, w)
    rid = cleanup_temporary(store, w, temporary_plan(store, w)["files"])["recovery_ids"][0]

    def fail(*args: Any, **kwargs: Any) -> None:
        """Raise the injected failure used by the test.

        Args:
            args: Positional arguments forwarded to the operation.
            kwargs: Keyword arguments forwarded to the operation.

        Raises:
            OSError: Raised by the test helper.
        """
        raise OSError("Injected publication failure")

    monkeypatch.setattr("dataforge.temporary_cleanup.os.link", fail)
    with pytest.raises(OSError):
        restore_temporary(store, w, rid)
    assert not path.exists()
    assert store.rows("SELECT 1 FROM temporary_recovery WHERE recovery_id=?", [rid])
    store.close()


def test_cleanup_ui_requires_selection_then_can_restore(tmp_path: Path) -> None:
    """Verify that cleanup ui requires selection then can restore.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from streamlit.testing.v1 import AppTest

    store = Store(tmp_path)
    w = store.create_workspace("Cleanup UI")
    path = orphan(store, w)

    def page(home: "Any", workspace: "Any") -> None:
        """Handle page for the test scenario.

        Args:
            home: Home value used by the test case.
            workspace: Workspace used by the test.
        """
        from dataforge.store import Store
        from ui.temporary_cleanup import _controls

        db = Store(home)
        _controls(db, workspace)
        db.close()

    try:
        app = AppTest.from_function(page, args=(tmp_path, w)).run()
        assert app.button[0].disabled and path.exists()
        app.multiselect[0].set_value([path.name]).run()
        next(b for b in app.button if b.label == "Clean selected temporary files").click().run()
        assert not app.exception and not path.exists() and app.success
        next(b for b in app.button if b.label == "Restore selected temporary file").click().run()
        assert not app.exception and path.exists() and app.success
    finally:
        store.close()
