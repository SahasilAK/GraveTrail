import io
import json
import shutil
import subprocess
import zipfile

from dataforge.exports import graph_data, graph_html, report_csv, report_html, source_bundle
from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.store import Store


def test_offline_graph_and_reports_escape_source():
    name = '</script><img src=x onerror=alert(1)>'
    g = LineageGraph([{"asset_id": "a", "name": name, "kind": "table", "temporary": False}], [])
    output = graph_html(g)
    assert name not in output
    assert "https://" not in output and "<svg" in output
    assert json.loads(json.dumps(graph_data(g)))["nodes"][0]["name"] == name
    assert "&lt;img" in report_html([{"file": "<img src=x>"}])
    assert "'=formula" in report_csv([{"file": "=formula"}])


def test_original_bundle(tmp_path):
    store = Store(tmp_path)
    w = store.create_workspace("A")
    original = b"select 1;\r\n"
    Importer(store, w).files([("nested/q.sql", original)], {".sql"})
    data = source_bundle(store, [f["file_id"] for f in store.files(w)])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.read("nested/q.sql") == original
    store.close()


def test_graph_javascript_is_valid():
    from dataforge.exports import GRAPH_JS
    if node := shutil.which("node"):
        result = subprocess.run([node, "--check"], input=GRAPH_JS, text=True, encoding="utf-8", capture_output=True)
        assert result.returncode == 0, result.stderr


def test_path_csv_rows_keep_order_evidence_and_boundary():
    from dataforge.exports import path_rows

    graph = LineageGraph([{"asset_id": n, "name": n} for n in ["a", "b", "c"]], [
        {"source_id": "a", "target_id": "b", "edge_id": "ab", "statement_id": "s1", "start_line": 3},
        {"source_id": "b", "target_id": "c", "edge_id": "bc", "statement_id": "s2", "start_line": 7}])
    rows = path_rows(graph.path_report("c"))
    assert [(r["step"], r["source"], r["target"], r["statement_id"]) for r in rows] == [
        (1, "a", "b", "s1"), (2, "b", "c", "s2")]
    assert all(r["boundary"] == "root" and r["path"] == "a -> b -> c" for r in rows)


def test_graph_appearance_is_shared_with_offline_export_and_keeps_full_identity():
    from dataforge.configuration import VisualizationSettings

    name = 'catalog.schema.a_very_long_table_name_for_a_real_engineering_job'
    graph = LineageGraph([{"asset_id": "a", "name": name, "kind": "table", "temporary": False}], [])
    appearance = VisualizationSettings(graph_labels="full", graph_palette="neutral", graph_edge_width=4)
    data = graph_data(graph, appearance)
    assert data["appearance"] == {"graph_labels": "full", "graph_palette": "neutral", "graph_edge_width": 4}
    assert data["nodes"][0]["width"] > graph_data(graph)["nodes"][0]["width"]
    assert data["nodes"][0]["name"] == name
    output = graph_html(graph, appearance)
    exported = json.loads(output.split('mountGraph(document.body,', 1)[1].rsplit(',null);', 1)[0])
    assert exported == data
    hidden = graph_data(graph, VisualizationSettings(graph_labels="hidden"))
    assert hidden["nodes"][0]["name"] == name


def test_graph_mount_supports_component_document_fragment_without_style():
    from dataforge.exports import GRAPH_JS

    if node := shutil.which("node"):
        # Streamlit supplies a ShadowRoot/DocumentFragment, not a styled HTML element.
        script = GRAPH_JS + r'''
const attributes={},properties={};
const elements={
  'svg':{setAttribute:(k,v)=>attributes[k]=v},
  '.stage':{replaceChildren:()=>{}}, '.detail':{},
  '.df-graph':{style:{setProperty:(k,v)=>properties[k]=v}},
  '.fit':{}, '.plus':{}, '.minus':{}, '.find':{}
};
mountGraph({querySelector:s=>elements[s]},
  {nodes:[],edges:[],appearance:{graph_edge_width:4}},null);
console.log(JSON.stringify({attributes,properties}));
'''
        result = subprocess.run([node], input=script, text=True, encoding="utf-8", capture_output=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["properties"]["--df-selected-edge-width"] == 6
