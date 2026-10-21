import io
import stat
import zipfile
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


def test_evidence_pins_original_version_after_reimport(workspace: Any) -> None:
    """Verify that evidence pins original version after reimport.

    Args:
        workspace: Workspace used by the test.
    """
    s, w = workspace
    imp = Importer(s, w)
    old = b"create table mart.x as select id from raw.a;"
    imp.files([("a.sql", old)], {".sql"})
    analyze(s, w)
    edge = s.edges(w)[0]
    imp.files([("a.sql", b"select 1;")], {".sql"})
    retained = s.edges(w)[0]
    assert s.original(edge["file_id"], retained["source_hash"]) == old
    assert s.file(edge["file_id"], retained["source_hash"])["raw_content"] == old.decode()


def test_failed_materialization_rolls_back(workspace: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that failed materialization rolls back.

    Args:
        workspace: Workspace used by the test.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        RuntimeError: Raised by the test helper.
    """
    import dataforge.services as services
    s, w = workspace
    imp = Importer(s, w)
    imp.files([("a.sql", b"create table mart.x as select id from raw.a;")], {".sql"})
    analyze(s, w)
    original_edges = s.edges(w)
    imp.files([("a.sql", b"create table mart.x as select id from raw.b;")], {".sql"})
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


def test_zip_symlink_and_expansion_limit(workspace: Any) -> None:
    """Verify that zip symlink and expansion limit.

    Args:
        workspace: Workspace used by the test.
    """
    s, w = workspace
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("symlink.sql")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "somewhere")
        z.writestr("bomb.sql", "a" * 100000)
    report = Importer(s, w).zip(out.getvalue(), {".sql"})
    assert report.accepted == 0 and report.skipped == 2


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


def test_parallel_parsing_matches_sequential_and_config_validation(workspace: Any) -> None:
    """Verify that parallel parsing matches sequential and config validation.

    Args:
        workspace: Workspace used by the test.
    """
    from pydantic import ValidationError

    from dataforge.configuration import ParsingSettings
    s, w = workspace
    Importer(s, w).files([(f"q{i}.sql", f"create table mart.t{i} as select id from raw.t{i};".encode()) for i in range(12)], {".sql"})
    analyze(s, w)
    expected = {(e["source_id"], e["target_id"]) for e in s.edges(w)}
    s.set_setting(w, "parse_workers", 4)
    result = analyze(s, w, force=True)
    assert result["analyzed"] == 12
    assert {(e["source_id"], e["target_id"]) for e in s.edges(w)} == expected
    with pytest.raises(ValidationError):
        ParsingSettings.model_validate({"dialect": ["invalid"]})
    with pytest.raises(ValidationError):
        ParsingSettings.model_validate({"dialect_by_folder": {"folder/": "unknown_vendor"}})
