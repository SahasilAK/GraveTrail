import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from dataforge.exports import graph_data, graph_html, report_csv, report_html, source_bundle
from dataforge.graph import LineageGraph
from dataforge.ingestion import Importer
from dataforge.store import Store


def test_offline_graph_and_reports_escape_source() -> None:
    """Verify that offline graph and reports escape source."""
    name = '</script><img src=x onerror=alert(1)>'
    g = LineageGraph([{"asset_id": "a", "name": name, "kind": "table", "temporary": False}], [])
    output = graph_html(g)
    assert "<title>GraveTrail lineage</title>" in output
    assert "<title>GraveTrail report</title>" in report_html([])
    assert name not in output
    assert "https://" not in output and "<svg" in output
    assert json.loads(json.dumps(graph_data(g)))["nodes"][0]["name"] == name
    assert "&lt;img" in report_html([{"file": "<img src=x>"}])
    assert "'=formula" in report_csv([{"file": "=formula"}])


def test_original_bundle(tmp_path: Path) -> None:
    """Verify that original bundle.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    store = Store(tmp_path)
    w = store.create_workspace("A")
    original = b"select 1;\r\n"
    Importer(store, w).files([("nested/q.sql", original)], {".sql"})
    data = source_bundle(store, [f["file_id"] for f in store.files(w)])
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.read("nested/q.sql") == original
    store.close()


def test_graph_javascript_is_valid() -> None:
    """Verify that graph javascript is valid."""
    from dataforge.exports import GRAPH_JS
    if node := shutil.which("node"):
        result = subprocess.run([node, "--check"], input=GRAPH_JS, text=True, encoding="utf-8", capture_output=True)
        assert result.returncode == 0, result.stderr


def test_path_csv_rows_keep_order_evidence_and_boundary() -> None:
    """Verify that path csv rows keep order evidence and boundary."""
    from dataforge.exports import path_rows

    graph = LineageGraph([{"asset_id": n, "name": n} for n in ["a", "b", "c"]], [
        {"source_id": "a", "target_id": "b", "edge_id": "ab", "statement_id": "s1", "start_line": 3},
        {"source_id": "b", "target_id": "c", "edge_id": "bc", "statement_id": "s2", "start_line": 7}])
    rows = path_rows(graph.path_report("c"))
    assert [(r["step"], r["source"], r["target"], r["statement_id"]) for r in rows] == [
        (1, "a", "b", "s1"), (2, "b", "c", "s2")]
    assert all(r["boundary"] == "root" and r["path"] == "a -> b -> c" for r in rows)


def test_graph_appearance_is_shared_with_offline_export_and_keeps_full_identity() -> None:
    """Verify that graph appearance is shared with offline export and keeps full identity."""
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


def test_graph_mount_supports_component_document_fragment_without_style() -> None:
    """Verify that graph mount supports component document fragment without style."""
    from dataforge.exports import GRAPH_JS

    if node := shutil.which("node"):
        # Streamlit supplies a ShadowRoot/DocumentFragment, not a styled HTML element.
        script = GRAPH_JS + r'''
const attributes={},properties={};
const elements={
  'svg':{setAttribute:(k,v)=>attributes[k]=v},
  '.stage':{replaceChildren:()=>{}}, '.detail':{},
  '.df-graph':{toggleAttribute(){},style:{setProperty:(k,v)=>properties[k]=v,removeProperty(){}}},
  '#df-arrow path':{setAttribute(){}},
  '.fit':{}, '.plus':{}, '.minus':{}, '.find':{}, '.fullscreen':{}, '.status':{}
};
mountGraph({querySelector:s=>elements[s]},
  {nodes:[],edges:[],bounds:[-80,-80,780,360],appearance:{graph_edge_width:4}},null);
console.log(JSON.stringify({attributes,properties}));
'''
        result = subprocess.run([node], input=script, text=True, encoding="utf-8", capture_output=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["properties"]["--df-selected-edge-width"] == 6


def test_graph_double_click_cancels_selection_and_copy_keeps_full_name() -> None:
    """Verify that graph double click cancels selection and copy keeps full name."""
    from dataforge.exports import GRAPH_JS

    if not (node := shutil.which("node")):
        import pytest
        pytest.skip("Node.js is required for graph event regression")
    script = GRAPH_JS + r'''
(async()=>{
  class Element {
    constructor(){this.children=[];this.attrs={};this.style={setProperty(){},removeProperty(){}};this.classList={add(){},remove(){}}}
    toggleAttribute(){}
    setAttribute(k,v){this.attrs[k]=v}
    appendChild(e){this.children.push(e)}
    replaceChildren(){this.children=[]}
    querySelectorAll(){return []}
    getComputedTextLength(){return 999}
  }
  const copied=[],selected=[],navigated=[];
  global.document={createElementNS:()=>new Element()};
  Object.defineProperty(global,'navigator',{value:{clipboard:{writeText:async text=>copied.push(text)}}});
  const elements=Object.fromEntries(['svg','.stage','.detail','.df-graph','.fit','.plus','.minus','.find','.fullscreen','.status','#df-arrow path'].map(k=>[k,new Element()]));
  const root={querySelector:s=>elements[s]};
  const container=elements['.df-graph'];let active=false;
  container.matches=()=>active;
  container.ownerDocument={fullscreenElement:{},addEventListener(){},removeEventListener(){},exitFullscreen:async()=>{active=false}};
  container.requestFullscreen=async()=>{active=true};
  mountGraph(root,{nodes:[{asset_id:'a',name:'catalog.schema.a_very_long_table_name',x:20,y:20,width:215,kind:'table'}],edges:[],bounds:[-80,-80,780,360]},
    v=>selected.push(v),v=>navigated.push(v));
  const node=elements['.stage'].children.find(e=>e.attrs.class==='node');
  node.onclick({detail:1});
  node.ondblclick({preventDefault(){}});
  const copy=elements['.stage'].children.find(e=>e.attrs.class==='copy-node');
  await copy.onclick({stopPropagation(){}});
  await elements['.fullscreen'].onclick();
  if(elements['.fullscreen'].textContent!=='Exit fullscreen')throw Error('Fullscreen label did not update in a shadow root');
  await elements['.fullscreen'].onclick();
  if(active)throw Error('Fullscreen did not exit');
  await new Promise(resolve=>setTimeout(resolve,400));
  console.log(JSON.stringify({copied,selected,navigated}));
})().catch(e=>{console.error(e);process.exit(1)});
'''
    result = subprocess.run([node], input=script, text=True, encoding="utf-8", capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "copied": ["catalog.schema.a_very_long_table_name"], "selected": [], "navigated": ["a"]}
