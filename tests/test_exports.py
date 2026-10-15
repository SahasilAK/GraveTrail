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
