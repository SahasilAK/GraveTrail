import io
import zipfile

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
