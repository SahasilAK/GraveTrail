import io
import stat
import zipfile

import pytest

from dataforge.ingestion import Importer, Limits
from dataforge.services import analyze
from dataforge.store import Store


@pytest.fixture
def workspace(tmp_path):
    s = Store(tmp_path)
    w = s.create_workspace("Hardening")
    yield s, w
    s.close()


def test_evidence_pins_original_version_after_reimport(workspace):
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


def test_failed_materialization_rolls_back(workspace, monkeypatch):
    import dataforge.services as services
    s, w = workspace
    imp = Importer(s, w)
    imp.files([("a.sql", b"create table mart.x as select id from raw.a;")], {".sql"})
    analyze(s, w)
    original_edges = s.edges(w)
    imp.files([("a.sql", b"create table mart.x as select id from raw.b;")], {".sql"})
    materialize = services._materialize

    def fail_after_writes(*args, **kwargs):
        materialize(*args, **kwargs)
        raise RuntimeError("Injected failure")
    monkeypatch.setattr(services, "_materialize", fail_after_writes)
    with pytest.raises(RuntimeError):
        analyze(s, w)
    assert s.edges(w) == original_edges
    assert s.runs(w)[0]["status"] == "failed"


def test_import_stops_reading_when_byte_budget_is_exhausted(workspace):
    s, w = workspace
    imported = Importer(s, w, limits=Limits(max_file_bytes=10, max_total_bytes=5))
    calls = []

    def read(i):
        calls.append(i)
        return b"select 1"
    report = imported._import([(f"{i}.sql", lambda i=i: read(i)) for i in range(100)], {".sql"}, "test", None, None)
    assert len(calls) == 1
    assert report.accepted == 0 and report.diagnostics


def test_zip_symlink_and_expansion_limit(workspace):
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


def test_analysis_snapshot_does_not_mix_concurrent_import_content(workspace):
    s, w = workspace
    imp = Importer(s, w)
    old = b"create table mart.b as select id from raw.old;"
    imp.files([("a.sql", b"select id from raw.a;"), ("b.sql", old)], {".sql"})

    def change_after_first(progress, path):
        if path == "a.sql":
            imp.files([("b.sql", b"create table mart.b as select id from raw.new;")], {".sql"})
    analyze(s, w, progress=change_after_first)
    edge = s.edges(w)[0]
    assert edge["code"] == old.decode()
    assert s.original(edge["file_id"], edge["source_hash"]) == old
    assert next(f for f in s.files(w) if f["relative_path"] == "b.sql")["parsing_status"] == "pending"


def test_parallel_parsing_matches_sequential_and_config_validation(workspace):
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
