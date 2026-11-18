import json
from pathlib import Path

import httpx
from focused_test_profiles import focused_profile

from dataforge.ingestion import Importer
from dataforge.services import analyze, column_report
from dataforge.store import Store


def test_explicit_jobs_isolate_temporary_assets_but_share_persistent_assets(tmp_path: Path) -> None:
    """Verify that explicit jobs isolate temporary assets but share persistent assets.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
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


def test_qualified_and_unqualified_temporary_schemas_are_isolated_by_job(tmp_path: Path) -> None:
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Scoped qualified declarations")
        store.set_setting(w, "job_by_folder", {"one/": "one", "two/": "two", "three/": "three"})
        Importer(store, w).files([
            ("one/q.sql", b"create temporary table stage(id int); create table mart.one as select * from stage;"),
            ("two/q.sql", b"create temporary table stage(batch_id int); create table mart.two as select * from stage;"),
            ("three/q.sql", b"create temporary table other.stage(other_id int); create table mart.three as select * from other.stage;"),
        ], {".sql"})
        analyze(store, w)
        stages = [a for a in store.assets(w) if a["name"] in {"stage", "other.stage"}]
        assert len(stages) == 3 and all(a["temporary"] for a in stages)
        expected = {("one", "stage"): "id", ("two", "stage"): "batch_id", ("three", "other.stage"): "other_id"}
        for asset in stages:
            metadata = json.loads(asset["metadata"])
            job = metadata["job_id"]
            assert metadata["schema_status"] == "declared"
            assert {e["relative_path"].split("/")[0] for e in metadata["schema_evidence"]} == {job}
            assert {r["column_name"] for r in column_report(store, w, asset["asset_id"])} == {
                expected.pop((job, asset["name"]))
            }
    finally:
        store.close()


def test_ai_merge_uses_source_job_not_last_matching_name(tmp_path: Path) -> None:
    """Verify that ai merge uses source job not last matching name.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from dataforge.llm import assist, merge_claims

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
        result = assist(store, w, focused_profile(provider="Ollama", base_url="http://localhost:11434", model="test"), fid, 1, 1, transport=transport)
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


def test_same_job_temporary_persistent_collision_keeps_read_unresolved(tmp_path: Path) -> None:
    """Verify that same job temporary persistent collision keeps read unresolved.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Ambiguous lifetime")
        store.set_setting(w, "default_job", "batch")
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


def test_persistent_output_stays_globally_resolvable_when_its_job_also_writes_temporary(tmp_path: Path) -> None:
    """Verify that persistent output stays globally resolvable when its job also writes temporary.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
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
