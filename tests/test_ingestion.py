import io
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from dataforge.ingestion import Importer, Limits
from dataforge.store import Store


def archive(entries: Any) -> Any:
    """Handle archive for the test scenario.

    Args:
        entries: Entries value used by the test case.

    Returns:
        Value produced for the test scenario.
    """
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return out.getvalue()


@pytest.fixture
def setup(tmp_path: Path) -> Iterator[Any]:
    """Handle setup for the test scenario.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path / "db")
    workspace = store.create_workspace("Test")
    yield store, workspace, Importer(store, workspace, allowed_roots=[tmp_path])
    store.close()


def test_zip_inventory_preserves_bytes_and_reports_duplicates(setup: Any) -> None:
    """Verify that zip inventory preserves bytes and reports duplicates.

    Args:
        setup: Setup value used by the test case.
    """
    store, w, importer = setup
    original = b"select * from raw.x;\r\n"
    report = importer.zip(archive([("nested/a.sql", original), ("b.sql", original),
                                   ("skip.txt", b"ignore")]), {".sql"})
    assert report.accepted == 2
    assert report.duplicates == 1
    assert report.skipped == 1
    files = store.files(w)
    assert len(files) == 2
    assert store.original(files[0]["file_id"]) == original
    assert files[0]["relative_path"] in {"nested/a.sql", "b.sql"}


@pytest.mark.parametrize("name", ["../evil.sql", "/evil.sql", "C:/evil.sql", "a/../../evil.sql"])
def test_zip_rejects_unsafe_paths(setup: Any, name: str) -> None:
    """Verify that zip rejects unsafe paths.

    Args:
        setup: Setup value used by the test case.
        name: Name value used by the test case.
    """
    store, w, importer = setup
    report = importer.zip(archive([(name, b"select 1;")]), {".sql"})
    assert report.accepted == 0
    assert report.skipped == 1
    assert report.diagnostics
    assert store.files(w) == []


def test_directory_root_and_extension_filter(setup: Any, tmp_path: Path) -> None:
    """Verify that directory root and extension filter.

    Args:
        setup: Setup value used by the test case.
        tmp_path: Temporary directory supplied by pytest.
    """
    store, w, importer = setup
    root = tmp_path / "sources"
    root.mkdir()
    (root / "a.sql").write_text("select * from raw.x")
    (root / "a.sas").write_text("data a; set b; run;")
    report = importer.directory(root, {".sas"})
    assert report.accepted == 1
    assert store.files(w)[0]["extension"] == ".sas"
    with pytest.raises(ValueError, match="allowed"):
        importer.directory(tmp_path.parent, {".sql"})


@pytest.mark.parametrize("location", ["outside", "prefix", "traversal", "relative", "no_roots"])
def test_directory_rejects_unapproved_paths_before_filesystem_access(setup: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str) -> None:
    """Verify that directory rejects unapproved paths before filesystem access.

    Args:
        setup: Setup value used by the test case.
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
        location: Location value used by the test case.

    Raises:
        AssertionError: Raised by the test helper.
    """
    store, w, _ = setup
    root = tmp_path / "allowed"
    root.mkdir()
    importer = Importer(store, w, allowed_roots=[] if location == "no_roots" else [root])
    paths = {"outside": tmp_path / "outside", "prefix": tmp_path / "allowed-private",
             "traversal": root / ".." / "outside", "relative": "outside", "no_roots": root}
    monkeypatch.chdir(tmp_path)

    def forbidden_access(*args: Any, **kwargs: Any) -> None:
        """Handle forbidden access for the test scenario.

        Args:
            args: Positional arguments forwarded to the operation.
            kwargs: Keyword arguments forwarded to the operation.

        Raises:
            AssertionError: Raised by the test helper.
        """
        raise AssertionError("Unapproved directory reached the filesystem")

    with monkeypatch.context() as guard:
        guard.setattr(Path, "resolve", forbidden_access)
        guard.setattr(Path, "is_dir", forbidden_access)
        guard.setattr("dataforge.ingestion.os.walk", forbidden_access)
        with pytest.raises(ValueError, match="allowed roots"):
            importer.directory(paths[location], {".sql"})
    assert store.files(w) == []


def test_directory_accepts_root_nested_normalized_relative_and_filesystem_root(setup: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that directory accepts root nested normalized relative and filesystem root.

    Args:
        setup: Setup value used by the test case.
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.
    """
    store, w, _ = setup
    root = tmp_path / "allowed"
    nested = root / "nested"
    nested.mkdir(parents=True)
    original = b"select * from raw.orders;\r\n"
    (nested / "a.sql").write_bytes(original)
    monkeypatch.chdir(tmp_path)
    for directory, roots in [(root, [root]), (nested, [root]), ("allowed/nested/../nested", [root]),
                              (nested, [Path(tmp_path.anchor)]), (nested, [tmp_path / "other", root])]:
        report = Importer(store, w, allowed_roots=roots).directory(directory, {".sql"})
        assert report.accepted == 1
    assert all(store.original(f["file_id"]) == original for f in store.files(w))


def test_directory_rejects_symlink_escape_and_does_not_read_linked_children(setup: Any, tmp_path: Path) -> None:
    """Verify that directory rejects symlink escape and does not read linked children.

    Args:
        setup: Setup value used by the test case.
        tmp_path: Temporary directory supplied by pytest.
    """
    store, w, _ = setup
    root, outside = tmp_path / "allowed", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "safe.sql").write_text("select 1", encoding="utf-8")
    (outside / "private.sql").write_text("select 'private'", encoding="utf-8")
    try:
        (root / "escape").symlink_to(outside, target_is_directory=True)
        (root / "linked.sql").symlink_to(outside / "private.sql")
    except OSError:
        pytest.skip("Creating symlinks requires OS permission")
    importer = Importer(store, w, allowed_roots=[root])
    with pytest.raises(ValueError, match="allowed roots"):
        importer.directory(root / "escape", {".sql"})
    report = importer.directory(root, {".sql"})
    assert report.accepted == 1
    assert [f["relative_path"] for f in store.files(w)] == ["safe.sql"]


def test_limits_binary_and_changed_path(setup: Any) -> None:
    """Verify that limits binary and changed path.

    Args:
        setup: Setup value used by the test case.
    """
    store, w, importer = setup
    importer.limits = Limits(max_file_bytes=50, max_total_bytes=100)
    report = importer.files([("big.sql", b"x" * 60), ("binary.sql", b"a\0b"),
                             ("good.sql", b"select 1")], {".sql"})
    assert report.accepted == 1
    assert report.skipped == 2
    importer.files([("good.sql", b"select 2")], {".sql"})
    assert len(store.files(w)) == 1
    assert store.file(store.files(w)[0]["file_id"])["raw_content"] == "select 2"
