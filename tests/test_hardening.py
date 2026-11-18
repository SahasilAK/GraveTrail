from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dataforge.ingestion import Importer, Limits
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Any]:
    """Provide the workspace fixture used by the tests.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    s = Store(tmp_path)
    w = s.create_workspace("Hardening")
    yield s, w
    s.close()


def test_reimport_pins_original_evidence_and_failed_materialization_rolls_back(
    workspace: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataforge.services as services
    s, w = workspace
    imp = Importer(s, w)
    old = b"create table mart.x as select id from raw.a;"
    imp.files([("a.sql", old)], {".sql"})
    analyze(s, w)
    original_edges = s.edges(w)
    imp.files([("a.sql", b"create table mart.x as select id from raw.b;")], {".sql"})
    retained, = s.edges(w)
    assert s.original(retained["file_id"], retained["source_hash"]) == old
    assert s.file(retained["file_id"], retained["source_hash"])["raw_content"] == old.decode()
    materialize = services._materialize

    def fail_after_writes(*args: Any, **kwargs: Any) -> None:
        """Handle fail after writes for the test scenario.

        Args:
            args: Positional arguments forwarded to the operation.
            kwargs: Keyword arguments forwarded to the operation.

        Raises:
            RuntimeError: Raised by the test helper.
        """
        materialize(*args, **kwargs)
        raise RuntimeError("Injected failure")
    monkeypatch.setattr(services, "_materialize", fail_after_writes)
    with pytest.raises(RuntimeError):
        analyze(s, w)
    assert s.edges(w) == original_edges
    assert s.runs(w)[0]["status"] == "failed"


def test_import_stops_reading_when_byte_budget_is_exhausted(workspace: Any) -> None:
    """Verify that import stops reading when byte budget is exhausted.

    Args:
        workspace: Workspace used by the test.
    """
    s, w = workspace
    imported = Importer(s, w, limits=Limits(max_file_bytes=10, max_total_bytes=5))
    calls = []

    def read(i: Any) -> bytes:
        """Handle read for the test scenario.

        Args:
            i: I value used by the test case.

        Returns:
            Value produced for the test scenario.
        """
        calls.append(i)
        return b"select 1"
    report = imported._import([(f"{i}.sql", lambda i=i: read(i)) for i in range(100)], {".sql"}, "test", None, None)
    assert len(calls) == 1
    assert report.accepted == 0 and report.diagnostics


def test_analysis_snapshot_does_not_mix_concurrent_import_content(workspace: Any) -> None:
    """Verify that analysis snapshot does not mix concurrent import content.

    Args:
        workspace: Workspace used by the test.
    """
    s, w = workspace
    imp = Importer(s, w)
    old = b"create table mart.b as select id from raw.old;"
    imp.files([("a.sql", b"select id from raw.a;"), ("b.sql", old)], {".sql"})

    def change_after_first(progress: Any, path: Any) -> None:
        """Handle change after first for the test scenario.

        Args:
            progress: Progress value used by the test case.
            path: Path value used by the test case.
        """
        if path == "a.sql":
            imp.files([("b.sql", b"create table mart.b as select id from raw.new;")], {".sql"})
    analyze(s, w, progress=change_after_first)
    edge = s.edges(w)[0]
    assert edge["code"] == old.decode()
    assert s.original(edge["file_id"], edge["source_hash"]) == old
    assert next(f for f in s.files(w) if f["relative_path"] == "b.sql")["parsing_status"] == "pending"
