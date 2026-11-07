from pathlib import Path

import pytest

from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.services import analyze, column_report
from dataforge.store import Store

FIXTURES = Path(__file__).parent / "fixtures" / "scenario"


@pytest.mark.parametrize('historical', [False, True])
def test_reopened_parser_upgrade_is_stale_in_reports_and_exports(tmp_path, monkeypatch, historical):
    from dataforge.agent.service import AgentService
    from dataforge.services import analysis_is_current, export_graph_image, export_lineage_excel

    store = Store(tmp_path)
    w = store.create_workspace('upgrade')
    Importer(store, w).files([('q.sql', b'create table dst as select id from raw.src')], {'.sql'})
    analyze(store, w)
    assert analysis_is_current(store, w)
    if historical:
        store.execute('DELETE FROM column_analysis WHERE workspace_id=?', [w])
    store.close()
    monkeypatch.setattr('dataforge.services.PARSER_VERSION', 'future-parser')
    store = Store(tmp_path)
    service = AgentService(store)
    try:
        assert not analysis_is_current(store, w)
        assert not service.call('lineage', w, asset='dst')['analysis_current']
        aid = next(a['asset_id'] for a in store.assets(w) if a['name'] == 'dst')
        assert not export_graph_image(store, w, aid)[1]['coverage']['analysis_current']
        excel = export_lineage_excel(store, w, aid)[1]
        assert not excel['complete']
        assert any('not current' in warning for warning in excel['warnings'])
        analyze(store, w)
        assert analysis_is_current(store, w)
    finally:
        service.close()
        store.close()


def test_full_persisted_workflow_and_incremental(tmp_path: Path) -> None:
    """Verify that full persisted workflow and incremental.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    w = store.create_workspace("Delivery")
    report = Importer(store, w, [FIXTURES]).directory(FIXTURES, {".sql", ".sas", ".csv"})
    assert report.accepted == 7
    run = analyze(store, w)
    assert run["analyzed"] == 7
    graph = LineageGraph(store.assets(w), store.edges(w))
    target = graph.search("mart.customer_summary")[0]["asset_id"]
    assert {graph.nodes[n]["name"].lower() for n in graph.focus(target, "upstream", 10).nodes} == {
        "file:input/customers.csv", "work.customers_stage", "staging.customers", "mart.customer_summary"}
    assert len(graph.search("orders")) == 3
    simplified = graph.simplified()
    source = graph.search("file:input/customers.csv")[0]["asset_id"]
    staging = graph.search("staging.customers")[0]["asset_id"]
    assert simplified.graph.has_edge(source, staging)
    assert len(simplified.graph[source][staging]["evidence"]) == 2
    assert all(e["code"] and e["start_line"] >= 1 for e in store.edges(w))
    assert graph.cycles()
    assert store.diagnostics(w)
    cols = column_report(store, w, staging)
    assert {u["column_name"] for u in cols} == {"customer_id", "customer_name", "active"}
    cached = analyze(store, w)
    assert cached["cached"] == 7 and cached["analyzed"] == 0
    before = len(store.edges(w))
    store.close()
    store = Store(tmp_path)
    assert len(store.edges(w)) == before
    assert len(store.runs(w)) == 2
    store.close()


def test_changed_source_removes_stale_lineage_and_isolation(tmp_path: Path) -> None:
    """Verify that changed source removes stale lineage and isolation.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    s = Store(tmp_path)
    w, other = s.create_workspace("A"), s.create_workspace("B")
    imp = Importer(s, w)
    imp.files([("a.sql", b"create table mart.x as select id from raw.a")], {".sql"})
    analyze(s, w)
    imp.files([("a.sql", b"create table mart.x as select id from raw.b")], {".sql"})
    analyze(s, w)
    names = {a["name"] for a in s.assets(w)}
    assert "raw.a" not in names and "raw.b" in names
    assert s.assets(other) == [] and s.edges(other) == []
    s.close()


def test_csv_name_alone_never_creates_dependency(tmp_path: Path) -> None:
    """Verify that csv name alone never creates dependency.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    s = Store(tmp_path)
    w = s.create_workspace("A")
    Importer(s, w).files([("customers.csv", b"id\n1"),
                           ("q.sql", b"create table mart.x as select id from customers")], {".sql", ".csv"})
    analyze(s, w)
    g = LineageGraph(s.assets(w), s.edges(w))
    csv = g.search("file:customers.csv")[0]["asset_id"]
    assert g.graph.degree(csv) == 0
    s.close()
