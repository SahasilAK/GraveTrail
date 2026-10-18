import io
import zipfile
from pathlib import Path

import pytest

from dataforge.ingestion import Importer, Limits
from dataforge.store import Store


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    return out.getvalue()


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "db")
    workspace = store.create_workspace("Test")
    yield store, workspace, Importer(store, workspace, allowed_roots=[tmp_path])
    store.close()


def test_zip_inventory_preserves_bytes_and_reports_duplicates(setup):
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
def test_zip_rejects_unsafe_paths(setup, name):
    store, w, importer = setup
    report = importer.zip(archive([(name, b"select 1;")]), {".sql"})
    assert report.accepted == 0
    assert report.skipped == 1
    assert report.diagnostics
    assert store.files(w) == []


def test_directory_root_and_extension_filter(setup, tmp_path):
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
def test_directory_rejects_unapproved_paths_before_filesystem_access(setup, tmp_path, monkeypatch, location):
    store, w, _ = setup
    root = tmp_path / "allowed"
    root.mkdir()
    importer = Importer(store, w, allowed_roots=[] if location == "no_roots" else [root])
    paths = {"outside": tmp_path / "outside", "prefix": tmp_path / "allowed-private",
             "traversal": root / ".." / "outside", "relative": "outside", "no_roots": root}
    monkeypatch.chdir(tmp_path)

    def forbidden_access(*args, **kwargs):
        raise AssertionError("Unapproved directory reached the filesystem")

    with monkeypatch.context() as guard:
        guard.setattr(Path, "resolve", forbidden_access)
        guard.setattr(Path, "is_dir", forbidden_access)
        guard.setattr("dataforge.ingestion.os.walk", forbidden_access)
        with pytest.raises(ValueError, match="allowed roots"):
            importer.directory(paths[location], {".sql"})
    assert store.files(w) == []


def test_directory_accepts_root_nested_normalized_relative_and_filesystem_root(setup, tmp_path, monkeypatch):
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


def test_directory_rejects_symlink_escape_and_does_not_read_linked_children(setup, tmp_path):
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


def test_limits_binary_and_changed_path(setup):
    store, w, importer = setup
    importer.limits = Limits(max_file_bytes=50, max_total_bytes=100)
    report = importer.files([("big.sql", b"x" * 60), ("binary.sql", b"a\0b"),
                             ("good.sql", b"select 1")], {".sql"})
    assert report.accepted == 1
    assert report.skipped == 2
    importer.files([("good.sql", b"select 2")], {".sql"})
    assert len(store.files(w)) == 1
    assert store.file(store.files(w)[0]["file_id"])["raw_content"] == "select 2"
