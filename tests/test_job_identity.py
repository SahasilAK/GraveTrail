import json

import httpx
import pytest

from dataforge.ingestion import Importer
from dataforge.models import stable_id
from dataforge.services import analyze, column_report
from dataforge.store import Store


def test_explicit_jobs_isolate_temporary_assets_but_share_persistent_assets(tmp_path):
    from dataforge.graph import LineageGraph

    store = Store(tmp_path)
    try:
        w = store.create_workspace("Jobs")
        store.set_setting(w, "job_by_folder", {"one/": "one", "two/": "two"})
        Importer(store, w).files([
            ("one/stage.sas", b"data work.stage; set raw.a; run;"),
            ("one/load.sql", b"create table mart.one as select id from work.stage;"),
            ("two/stage.sas", b"data work.stage; set raw.b; run;"),
            ("two/load.sql", b"create table mart.two as select id from work.stage;"),
            ("two/shared.sql", b"create table mart.three as select id from mart.one;")], {".sas", ".sql"})
        analyze(store, w)
        assets = store.assets(w)
        temporary = [a for a in assets if a["name"] == "work.stage"]
        assert len(temporary) == 2
        assert {json.loads(a["metadata"])["job_id"] for a in temporary} == {"one", "two"}
        graph = LineageGraph(assets, store.edges(w))
        root = next(a["asset_id"] for a in assets if a["name"] == "raw.a")
        names = {a["name"] for a in graph.focus(root, "downstream").nodes.values()}
        assert "mart.one" in names and "mart.two" not in names
        assert "mart.three" in names  # persistent cross-job dependency remains shared
        for asset in temporary:
            job = json.loads(asset["metadata"])["job_id"]
            assert {r["relative_path"].split("/")[0] for r in column_report(store, w, asset["asset_id"])} == {job}
    finally:
        store.close()


def test_workspace_default_preserves_legacy_asset_ids_and_job_settings_roundtrip(tmp_path):
    from dataforge.configuration import (
        ParsingSettings,
        export_workspace_configuration,
        import_workspace_configuration,
    )

    store = Store(tmp_path)
    try:
        w = store.create_workspace("Legacy")
        Importer(store, w).files([("q.sas", b"data work.x; set raw.a; run;")], {".sas"})
        analyze(store, w)
        assert next(a for a in store.assets(w) if a["name"] == "work.x")["asset_id"] == stable_id(w, "work.x")
        for setting in [dict(default_job=""), dict(default_job="../bad"), dict(job_by_folder={"../": "job"})]:
            with pytest.raises(ValueError):
                ParsingSettings(**setting)
        store.set_setting(w, "default_job", "batch-1")
        store.set_setting(w, "job_by_folder", {"jobs/": "batch-2"})
        copied = import_workspace_configuration(store, export_workspace_configuration(store, w))
        assert store.setting(copied, "default_job") == "batch-1"
        assert store.setting(copied, "job_by_folder") == {"jobs/": "batch-2"}
    finally:
        store.close()


def test_job_changes_remain_visible_in_history_and_exports(tmp_path):
    from dataforge.exports import graph_data
    from dataforge.graph import LineageGraph
    from dataforge.services import compare_runs

    store = Store(tmp_path)
    try:
        w = store.create_workspace("Job history")
        Importer(store, w).files([("q.sas", b"data work.stage; set raw.a; run; data mart.x; set work.stage; run;")], {".sas"})
        store.set_setting(w, "default_job", "one")
        analyze(store, w)
        first = store.runs(w)[0]
        store.set_setting(w, "default_job", "two")
        analyze(store, w)
        difference = compare_runs(first, store.runs(w)[0])
        assert difference["removed_assets"] == ["work.stage [job: one]"]
        assert difference["added_assets"] == ["work.stage [job: two]"]
        graph = LineageGraph(store.assets(w), store.edges(w))
        node = next(a for a in graph_data(graph)["nodes"] if a["name"] == "work.stage")
        assert node["job_id"] == "two"
        assert "work.stage [job: two]" in graph.simplified().lineage_rows()[0]["intermediates"]
    finally:
        store.close()


def test_sql_temporary_schema_is_not_shared_between_jobs(tmp_path):
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Scoped schemas")
        store.set_setting(w, "job_by_folder", {"one/": "one", "two/": "two"})
        Importer(store, w).files([
            ("one/q.sql", b"create temporary table stage(id int); create table mart.one as select * from stage;"),
            ("two/q.sql", b"create temporary table stage(other_id int); create table mart.two as select * from stage;")], {".sql"})
        analyze(store, w)
        temps = [a for a in store.assets(w) if a["name"] == "stage"]
        assert len(temps) == 2
        columns = {json.loads(a["metadata"])["job_id"]: {r["column_name"] for r in column_report(store, w, a["asset_id"])} for a in temps}
        assert columns == {"one": {"id"}, "two": {"other_id"}}
    finally:
        store.close()


def test_qualified_temporary_schema_in_other_job_cannot_invalidate_or_create_assets(tmp_path):
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Scoped qualified declarations")
        store.set_setting(w, "job_by_folder", {"one/": "one", "two/": "two"})
        Importer(store, w).files([
            ("one/q.sql", b"create temporary table stage(id int); create table mart.one as select * from stage;"),
            ("two/q.sql", b"create temporary table other.stage(other_id int); create table mart.two as select * from other.stage;")], {".sql"})
        analyze(store, w)
        stages = [a for a in store.assets(w) if a["name"] in {"stage", "other.stage"}]
        assert len(stages) == 2 and all(a["temporary"] for a in stages)
        for asset in stages:
            metadata = json.loads(asset["metadata"])
            assert metadata["schema_status"] == "declared"
            assert {e["relative_path"].split("/")[0] for e in metadata["schema_evidence"]} == {metadata["job_id"]}
            assert {r["column_name"] for r in column_report(store, w, asset["asset_id"])} == ({"id"} if metadata["job_id"] == "one" else {"other_id"})
    finally:
        store.close()


def test_ai_merge_uses_source_job_not_last_matching_name(tmp_path):
    from dataforge.llm import Profile, assist, merge_claims

    store = Store(tmp_path)
    try:
        w = store.create_workspace("AI scoped merge")
        store.set_setting(w, "job_by_folder", {"one/": "one", "two/": "two"})
        code = "create table mart.one as select id from work.stage;"
        Importer(store, w).files([("one/stage.sas", b"data work.stage; set raw.a; run;"),
            ("two/stage.sas", b"data work.stage; set raw.b; run;"), ("one/load.sql", code.encode())], {".sas", ".sql"})
        analyze(store, w)
        fid = next(f["file_id"] for f in store.files(w) if f["relative_path"] == "one/load.sql")
        body = {"claims": [{"source": "work.stage", "target": "mart.one", "operation": "CREATE",
            "start_line": 1, "end_line": 1, "quote": code, "explanation": "Direct", "confidence": .9}]}
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"message": {"content": json.dumps(body)}}))
        result = assist(store, w, Profile(provider="Ollama", base_url="http://localhost:11434", model="test"), fid, 1, 1, transport=transport)
        assert result["outcome"] == "validated"
        merge_claims(store, w, result["record_id"])
        edge = next(e for e in store.edges(w) if e["method"] == "llm")
        source = next(a for a in store.assets(w) if a["asset_id"] == edge["source_id"])
        assert json.loads(source["metadata"])["job_id"] == "one"
        analyze(store, w)
        assert next(e for e in store.edges(w) if e["method"] == "llm")["source_id"] == edge["source_id"]
        store.set_setting(w, "job_by_folder", {"one/": "changed", "two/": "two"})
        analyze(store, w)
        assert not [e for e in store.edges(w) if e["method"] == "llm"]
    finally:
        store.close()


@pytest.mark.parametrize("job", ["workspace", "batch"])
def test_same_job_temporary_persistent_collision_keeps_read_unresolved(tmp_path, job):
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Ambiguous lifetime")
        store.set_setting(w, "default_job", job)
        Importer(store, w).files([("q.sql", b"create temporary table stage as select id from raw.a;\ncreate table stage as select id from raw.b;\ncreate table mart.x as select * from stage;")], {".sql"})
        analyze(store, w)
        unresolved = [a for a in store.assets(w) if a["kind"] == "unresolved"]
        assert len(unresolved) == 1
        concrete = [a for a in store.assets(w) if a["name"] == "stage" and a["kind"] != "unresolved"]
        assert len(concrete) == 2 and {a["temporary"] for a in concrete} == {True, False}
        assert any("read identity unresolved" in d["message"] for d in store.diagnostics(w))
        row = column_report(store, w, unresolved[0]["asset_id"])[0]
        assert row["column_name"] == "*" and row["status"] == "unresolved"
        edges = [e for e in store.edges(w) if e["source_id"] == unresolved[0]["asset_id"]]
        assert edges and all(e["status"] == "unresolved" for e in edges)
    finally:
        store.close()


def test_settings_ui_saves_job_assignment_and_distinct_asset_choices(tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve()).run()
    w = app.session_state["workspace"]
    app.switch_page("ui/pages/settings.py").run()
    next(t for t in app.text_input if t.label == "Default job/session ID").set_value("daily")
    next(t for t in app.text_area if t.label == "Job/session by folder prefix (JSON)").set_value('{"one/":"one","two/":"two"}')
    next(b for b in app.button if b.label == "Save parsing settings").click().run()
    assert app.success and not app.exception
    store = Store(tmp_path)
    try:
        assert store.setting(w, "default_job") == "daily"
        assert store.setting(w, "job_by_folder") == {"one/": "one", "two/": "two"}
        Importer(store, w).files([("one/q.sas", b"data work.stage; set raw.a; run;"),
                                 ("two/q.sas", b"data work.stage; set raw.b; run;")], {".sas"})
        analyze(store, w)
        app.switch_page("ui/pages/explorer.py").run()
        assert not app.exception
        chooser = next(s for s in app.selectbox if s.label == "Choose an exact asset")
        assert any("work.stage [job: one]" in option for option in chooser.options)
        assert any("work.stage [job: two]" in option for option in chooser.options)
    finally:
        store.close()


@pytest.mark.parametrize("declaration", ["", "create table stage as select id from raw.b;"])
def test_default_temporary_and_foreign_job_persistent_writes_keep_separate_paths(tmp_path, declaration):
    from dataforge.graph import LineageGraph

    store = Store(tmp_path)
    try:
        w = store.create_workspace("Mixed lifetime jobs")
        store.set_setting(w, "job_by_folder", {"two/": "two"})
        Importer(store, w).files([
            ("one.sql", b"create temporary table stage as select id from raw.a;"),
            ("two/q.sql", (declaration + " create table mart.x as select id from stage;").encode())], {".sql"})
        analyze(store, w)
        assets = store.assets(w)
        assert len([a for a in assets if a["name"] == "stage"]) == 2
        graph = LineageGraph(assets, store.edges(w))
        root = next(a["asset_id"] for a in assets if a["name"] == "raw.a")
        assert "mart.x" not in {a["name"] for a in graph.focus(root, "downstream").nodes.values()}
    finally:
        store.close()


def test_persistent_output_stays_globally_resolvable_when_its_job_also_writes_temporary(tmp_path):
    from dataforge.graph import LineageGraph

    store = Store(tmp_path)
    try:
        w = store.create_workspace("Global persistent output")
        store.set_setting(w, "job_by_folder", {"one/": "one", "two/": "two"})
        Importer(store, w).files([
            ("one/q.sql", b"create temporary table mart.stage as select id from raw.a; create table mart.stage as select id from raw.b;"),
            ("two/q.sql", b"create table mart.final as select id from stage;")], {".sql"})
        analyze(store, w)
        assets = store.assets(w)
        assert not [a for a in assets if a["name"] == "stage"]
        graph = LineageGraph(assets, store.edges(w))
        for source, expected in [("raw.a", False), ("raw.b", True)]:
            root = next(a["asset_id"] for a in assets if a["name"] == source)
            assert ("mart.final" in {a["name"] for a in graph.focus(root, "downstream").nodes.values()}) == expected
    finally:
        store.close()
