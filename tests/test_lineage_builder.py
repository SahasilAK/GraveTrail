import io
import json
import zipfile

import pytest
from pydantic import ValidationError


def test_schema_imports_common_formats():
    from dataforge.schema_imports import import_schema

    fixtures = [
        ("tables.sql", b"CREATE TABLE raw.people (id INT, name VARCHAR(30));", "raw.people"),
        ("schema.yml", b"version: 2\nmodels:\n- name: people\n  columns:\n  - name: id\n    data_type: int\n", "people"),
        ("manifest.json", json.dumps({"nodes": {"model.x": {"resource_type": "model", "name": "people", "columns": {"id": {"name": "id", "data_type": "int"}}}}}).encode(), "people"),
        ("schema.csv", b"table,column,data_type,comment\npeople,id,int,Identifier\n", "people"),
        ("export.xml", b'<POWERMART><SOURCE NAME="people"><SOURCEFIELD NAME="id" DATATYPE="integer"/></SOURCE></POWERMART>', "people"),
        ("tables.sas", b"data people; length id 8 name $30; run;", "people"),
    ]
    for name, content, expected in fixtures:
        tables, warnings = import_schema(name, content)
        assert tables[0].name == expected, (name, warnings)
        assert tables[0].columns[0].name == "id"
    tables, _ = import_schema("labels.sas", b'data people; length id 8; label id="length fake 20;"; run;')
    assert [c.name for c in tables[0].columns] == ["id"]
    with pytest.raises(ValueError):
        import_schema("large.csv", b"table,column,comment\npeople,id," + b"x" * 140000)
    with pytest.raises(ValueError, match="No.*schema"):
        import_schema("query.sql", b"SELECT * FROM unknown;")
    with pytest.raises(ValueError):
        import_schema("unsafe.xml", b'<!DOCTYPE x [<!ENTITY x "y">]><SOURCE NAME="x"/>')


def test_builder_persistence_links_and_exports(tmp_path):
    from dataforge.lineage_builder import (
        BuilderDocument,
        BuilderLink,
        BuilderTable,
        export_tabular,
        load_builder,
        save_builder,
    )
    from dataforge.store import Store

    store = Store(tmp_path)
    try:
        workspace = store.create_workspace("Design")
        other = store.create_workspace("Other")
        a = BuilderTable(name="raw.people", columns=[{"name": "id", "data_type": "INT"}], position={"x": 20, "y": 40})
        b = BuilderTable(name="mart.people", role="target", columns=[{"name": "id"}], position={"x": 430, "y": 40})
        edge = BuilderLink(source_table=a.id, source_column=a.columns[0].id, target_table=b.id, target_column=b.columns[0].id, label="Join")
        doc = BuilderDocument(tables=[a, b], links=[edge])
        saved = save_builder(store, workspace, doc)
        assert load_builder(store, workspace) == saved
        assert load_builder(store, other).tables == []
        with pytest.raises(ValueError, match="changed"):
            save_builder(store, workspace, doc)
        restored = BuilderDocument.model_validate_json(saved.model_dump_json())
        assert restored.links[0].label == "Join"
        assert b"raw.people" in export_tabular(restored, "csv")
        with zipfile.ZipFile(io.BytesIO(export_tabular(restored, "xlsx"))) as archive:
            assert "xl/worksheets/sheet2.xml" in archive.namelist()
        broken = restored.model_dump()
        broken["tables"][1]["columns"] = []
        with pytest.raises(ValidationError):
            BuilderDocument.model_validate(broken)
    finally:
        store.close()


def test_html_export_is_offline_and_escapes_imported_labels():
    from dataforge.lineage_builder import BuilderDocument, BuilderTable
    from ui.builder_canvas import builder_html

    doc = BuilderDocument(tables=[BuilderTable(name="</script><script>alert(1)</script>", columns=[{"name": "id"}], position={"x": 0, "y": 0})])
    output = builder_html(doc).decode()
    assert "https://" not in output
    assert "</script><script>alert(1)" not in output
    assert "\\u003c/script" in output


def test_builder_sidebar_create_and_canvas(tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from dataforge.lineage_builder import load_builder
    from ui.common import get_store

    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=20).run()
    app.switch_page("ui/pages/lineage_builder.py").run()
    assert not app.exception
    next(c for c in app.selectbox if c.label == "System / database").set_value("SQL Server").run()
    next(t for t in app.text_input if t.label == "Table name").set_value("new_table")
    next(b for b in app.button if b.label == "Create table").click().run()
    assert not app.exception
    store = get_store(str(tmp_path))
    assert load_builder(store, app.session_state["workspace"]).tables[0].name == "new_table"
    assert load_builder(store, app.session_state["workspace"]).tables[0].system == "SQL Server"
    assert load_builder(store, app.session_state["workspace"]).tables[0].canvas_member
    assert load_builder(store, app.session_state["workspace"]).tables[0].position is None
    app.segmented_control[0].set_value("Build lineage").run()
    assert not app.exception
    next(c for c in app.selectbox if c.label == "Builder export format").set_value("HTML").run()
    next(b for b in app.button if b.label == "Prepare builder export").click().run()
    assert not app.exception
    assert len(app.get("download_button")) == 1
    app.segmented_control[0].set_value("Export schemas").run()
    next(c for c in app.selectbox if c.label == "Tables to export").set_value("Selected tables").run()
    next(c for c in app.multiselect if c.label == "Search and select tables").set_value([
        load_builder(store, app.session_state["workspace"]).tables[0].id]).run()
    next(c for c in app.selectbox if c.label == "Schema export format").set_value("CSV").run()
    next(b for b in app.button if b.label == "Prepare schema export").click().run()
    assert not app.exception
    assert any(b.label == "Download schemas CSV" for b in app.get("download_button"))
    app.segmented_control[0].set_value("Saved work").run()
    next(t for t in app.text_input if t.label == "Work name").set_value("Design one").run()
    next(b for b in app.button if b.label == "Save new work").click().run()
    assert not app.exception
    assert any(b.label == "Export saved work JSON" for b in app.get("download_button"))


def test_free_canvas_positions_and_column_fanout():
    from dataforge.lineage_builder import BuilderDocument, BuilderTable

    source = BuilderTable(name="source", columns=[{"name": "id"}], position={"x": -450, "y": -250})
    targets = [BuilderTable(name=name, columns=[{"name": "id"}]) for name in ("a", "b")]
    links = [{"source_table": source.id, "source_column": source.columns[0].id,
              "target_table": t.id, "target_column": t.columns[0].id} for t in targets]
    links.append({"source_table": targets[0].id, "source_column": targets[0].columns[0].id,
                  "target_table": source.id, "target_column": source.columns[0].id})
    doc = BuilderDocument(tables=[source, *targets], links=links)
    assert len(doc.links) == 3
    assert BuilderDocument.model_validate_json(doc.model_dump_json()).tables[0].position.x == -450
    with pytest.raises(ValidationError):
        BuilderDocument(tables=[source], links=[], revision=0).tables[0].position.y = float("inf")
    with pytest.raises(ValidationError):
        BuilderDocument(tables=doc.tables, links=[*doc.links, doc.links[0]])


def test_system_datatypes_and_decimal_entry():
    from dataforge.datatypes import format_data_type, type_entry
    from dataforge.lineage_builder import BuilderDocument, BuilderTable, columns_from_rows, export_tabular

    for system, kind, precision, scale, expected in [
        ("SQL Server", "DECIMAL", 18, 4, "DECIMAL(18,4)"),
        ("BigQuery", "NUMERIC", 38, 9, "NUMERIC(38,9)"),
        ("Oracle", "NUMBER", 12, -2, "NUMBER(12,-2)"),
        ("PostgreSQL", "NUMERIC", 3, 5, "NUMERIC(3,5)"),
        ("Databricks", "decimal(12,2)", None, None, "DECIMAL(12,2)"),
        ("SAS", "NUMERIC", None, None, "NUMERIC"),
    ]:
        assert format_data_type(system, kind, precision, scale) == expected
    for system, kind, precision, scale in [("SQL Server", "DECIMAL", None, None),
                                            ("SQL Server", "DECIMAL", 39, 0),
                                            ("Databricks", "DECIMAL", 5, 6),
                                            ("BigQuery", "NUMERIC", 38, 0)]:
        with pytest.raises(ValueError):
            format_data_type(system, kind, precision, scale)
    assert type_entry("DECIMAL(12,2)") == {"data_type": "DECIMAL", "precision": 12, "scale": 2}
    row = {"name": "amount", **type_entry("DECIMAL(12,2)")}
    columns = columns_from_rows([row, {"name": "location", "data_type": "MY_GEOGRAPHY"}], "SQL Server")
    table = BuilderTable(name="sales", system="SQL Server", columns=columns)
    doc = BuilderDocument(tables=[table])
    assert [c.data_type for c in table.columns] == ["DECIMAL(12,2)", "MY_GEOGRAPHY"]
    assert b"SQL Server" in export_tabular(doc, "csv")
    assert BuilderDocument.model_validate_json(doc.model_dump_json()).tables[0].system == "SQL Server"
    for system, original in [("Oracle", "NUMBER"), ("BigQuery", "NUMERIC"),
                             ("PostgreSQL", "NUMERIC"), ("Generic SQL", "NUMERIC(100,0)")]:
        imported = BuilderTable(name="existing", columns=[{"name": "amount", "data_type": original}])
        row = {**imported.columns[0].model_dump(), **type_entry(original, system), "comment": "Updated comment"}
        edited = columns_from_rows([row], system, existing=imported.columns)
        assert edited[0].data_type == original
        assert edited[0].comment == "Updated comment"


def test_canvas_joins_membership_and_shared_node_palette(tmp_path):
    from dataforge.lineage_builder import (
        BuilderDocument,
        BuilderLink,
        BuilderTable,
        export_tabular,
        load_builder,
        save_builder,
    )
    from dataforge.store import Store
    from dataforge.theme_configuration import PALETTES
    from ui.builder_canvas import builder_node_colors

    a = BuilderTable(name="customers", columns=[{"name": "id"}], position={"x": 20, "y": 20})
    b = BuilderTable(name="products", columns=[{"name": "customer_id"}], position={"x": 20, "y": 300})
    unused = BuilderTable(name="unused", columns=[])
    join = BuilderLink(source_table=a.id, source_column=a.columns[0].id, target_table=b.id,
                       target_column=b.columns[0].id, kind="join", join_type="Left join", label="Customer match")
    doc = BuilderDocument(tables=[a, b, unused], links=[join])
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Join design")
        doc = save_builder(store, w, doc)
        doc.tables[0].position = None
        doc.tables[0].canvas_member = False  # Removing/undoing placement must retain the catalog entry.
        saved = save_builder(store, w, doc)
        assert load_builder(store, w).tables[0].canvas_member
        assert not saved.tables[2].canvas_member
        saved.tables[1].catalog_hidden = True
        hidden = save_builder(store, w, saved)
        assert load_builder(store, w).tables[1].catalog_hidden
        assert hidden.tables[1].position is not None and hidden.links == saved.links
        assert BuilderDocument.model_validate_json(hidden.model_dump_json()).tables[1].catalog_hidden
        hidden.tables[1].color = "#2563eb"
        colored = save_builder(store, w, hidden)
        assert load_builder(store, w).tables[1].color == "#2563eb"
        assert BuilderDocument.model_validate_json(colored.model_dump_json()).tables[1].color == "#2563eb"
        with pytest.raises(ValidationError):
            colored.tables[1].color = "url(javascript:alert(1))"
        assert b"Left join" in export_tabular(saved, "csv")
        assert BuilderDocument.model_validate_json(saved.model_dump_json()).links[0].kind == "join"
        reversed_join = {**join.model_dump(), "id": "reverse", "source_table": b.id,
                         "source_column": b.columns[0].id, "target_table": a.id, "target_column": a.columns[0].id}
        with pytest.raises(ValidationError):
            BuilderDocument(tables=saved.tables, links=[join, reversed_join])
    finally:
        store.close()
    colors = builder_node_colors("Crimson Forge", "semantic")
    assert colors["source"]["stroke"] == PALETTES["Crimson Forge"]["source"]
    assert colors["source"]["fill"] == "#143e29"
    neutral = builder_node_colors("Crimson Forge", "neutral")
    assert neutral["source"] == neutral["intermediate"] == neutral["target"]


def test_resizable_tables_and_filtered_schema_exports():
    from dataforge.lineage_builder import BuilderDocument, BuilderTable, export_schemas
    from dataforge.schema_imports import import_schema

    a = BuilderTable(name="raw.people", columns=[{"name": "id", "data_type": "INT", "comment": "Full comment\nnext line"}],
                     size={"width": 600, "height": 250})
    b = BuilderTable(name="mart.people", role="target", columns=[{"name": "id", "data_type": "INT"}])
    doc = BuilderDocument(tables=[a, b])
    assert BuilderDocument.model_validate_json(doc.model_dump_json()).tables[0].size.width == 600
    assert b.size is None  # Old documents keep the automatic size.
    with pytest.raises(ValidationError):
        BuilderTable(name="bad", size={"width": 0, "height": 100})
    for format, extension in [("json", "json"), ("yaml", "yaml"), ("sql", "sql"), ("csv", "csv")]:
        content = export_schemas(doc, format, table_ids=[a.id])
        tables, _ = import_schema("schema." + extension, content)
        assert [t.name for t in tables] == ["raw.people"]
        assert tables[0].columns[0].data_type.upper() in ("INT", "INTEGER")
        if format != "sql":
            assert tables[0].columns[0].comment == a.columns[0].comment
    assert [t["name"] for t in json.loads(export_schemas(doc, "json", role="target"))["tables"]] == ["mart.people"]
    assert len(json.loads(export_schemas(doc, "json"))["tables"]) == 2
    with zipfile.ZipFile(io.BytesIO(export_schemas(doc, "xlsx", role="source"))) as archive:
        assert "xl/worksheets/sheet1.xml" in archive.namelist()
        assert "xl/worksheets/sheet2.xml" not in archive.namelist()
    with pytest.raises(ValueError, match="Select"):
        export_schemas(doc, "csv", table_ids=[])
    for system, datatype in [("SQL Server", "NVARCHAR(30)"), ("Oracle", "LONG RAW"), ("BigQuery", "STRING"),
                             ("PostgreSQL", "custom.geography"), ("DB2", "INT")]:
        table = BuilderTable(name="vendor.types", system=system, columns=[{"name": "value", "data_type": datatype}])
        assert datatype in export_schemas(BuilderDocument(tables=[table]), "sql").decode()
    for datatype in ["FOO); DROP TABLE x; --", "INT); DROP TABLE x; --", "INT DEFAULT 3"]:
        table = BuilderTable(name="unsafe", columns=[{"name": "value", "data_type": datatype}])
        with pytest.raises(ValueError, match="datatype"):
            export_schemas(BuilderDocument(tables=[table]), "sql")


def test_catalog_folders_and_saved_work_transfer(tmp_path):
    from dataforge.lineage_builder import (
        BuilderDocument,
        BuilderTable,
        list_builder_works,
        load_builder,
        load_builder_work,
        save_builder,
        save_builder_work,
    )
    from dataforge.store import Store

    doc = BuilderDocument(folders=[{"id": "sources", "name": "Source systems"}], tables=[
        BuilderTable(name="customers", folder="sources", canvas_member=True, color="#2563eb", columns=[{"name": "id"}],
                     position={"x": 20, "y": 30}, size={"width": 600, "height": 180})])
    with pytest.raises(ValidationError, match="folder"):
        BuilderDocument(tables=doc.tables)
    with pytest.raises(ValidationError):
        BuilderDocument(folders=[{"name": "Sales"}, {"name": "sales"}])
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Designer")
        other = store.create_workspace("Recipient")
        saved = save_builder(store, w, doc)
        work = save_builder_work(store, w, "Customer lineage")
        saved.tables[0].position.x = 200
        save_builder(store, w, saved)
        assert work.document.tables[0].position.x == 20
        imported = BuilderDocument.model_validate_json(work.document.model_dump_json())
        received = save_builder_work(store, other, "Received design", document=imported)
        assert received.document.folders[0].name == "Source systems"
        assert received.document.tables[0].folder == "sources"
        assert received.document.tables[0].size.width == 600
        assert received.document.tables[0].color == "#2563eb"
        assert load_builder(store, other).tables == []  # Import saves a copy until explicitly loaded.
        load_builder_work(store, other, received.id, expected_revision=0)
        assert load_builder(store, other).tables[0].position.x == 20
        assert len(list_builder_works(store, other)) == 1
        with pytest.raises(ValueError, match="revision|changed"):
            load_builder_work(store, other, received.id, expected_revision=0)
        with pytest.raises(ValueError, match="name|exists"):
            save_builder_work(store, w, "Customer lineage")
        updated = save_builder_work(store, w, "Updated design", work_id=work.id)
        assert updated.document.tables[0].position.x == 200
        assert len(list_builder_works(store, w)) == 1
        from dataforge.schema_imports import import_schema
        tables, _ = import_schema("schemas.json", work.document.model_dump_json().encode())
        assert tables[0].folder is None
        assert tables[0].color == ""
        with pytest.raises(ValueError):
            save_builder_work(store, w, "Broken", document=doc.model_copy(update={"folders": []}))
    finally:
        store.close()


def test_canvas_save_and_clear_preserve_work_atomically(tmp_path, monkeypatch):
    from dataforge.lineage_builder import (
        BuilderDocument,
        BuilderLink,
        BuilderTable,
        get_builder_work,
        list_builder_works,
        load_builder,
        load_builder_work,
        save_builder,
        save_canvas_work,
    )
    from dataforge.store import Store

    a = BuilderTable(name="source", folder="group", color="#2563eb", position={"x": 10, "y": 20}, columns=[{"name": "id"}])
    b = BuilderTable(name="target", role="target", position={"x": 600, "y": 20}, columns=[{"name": "id"}])
    doc = BuilderDocument(tables=[a, b], folders=[{"id": "group", "name": "Group"}], links=[
        BuilderLink(source_table=a.id, source_column=a.columns[0].id, target_table=b.id, target_column=b.columns[0].id)])
    store = Store(tmp_path)
    try:
        w = store.create_workspace("Canvas controls")
        doc = save_builder(store, w, doc)
        named = save_canvas_work(store, w, "My design", expected_revision=doc.revision)
        assert named.document == doc and load_builder(store, w) == doc
        with pytest.raises(ValueError, match="name|exists"):
            save_canvas_work(store, w, "My design", expected_revision=doc.revision, clear=True)
        with pytest.raises(ValueError, match="changed"):
            save_canvas_work(store, w, expected_revision=0, clear=True)
        assert load_builder(store, w) == doc and len(list_builder_works(store, w)) == 1
        original_set = store.set_setting

        def fail_clear(workspace, key, value):
            if key == "lineage_builder":
                raise OSError("Storage unavailable")
            original_set(workspace, key, value)

        with monkeypatch.context() as patch:
            patch.setattr(store, "set_setting", fail_clear)
            with pytest.raises(OSError):
                save_canvas_work(store, w, expected_revision=doc.revision, clear=True)
        assert load_builder(store, w) == doc and len(list_builder_works(store, w)) == 1
        backup = save_canvas_work(store, w, expected_revision=doc.revision, clear=True)
        empty = load_builder(store, w)
        assert get_builder_work(store, w, backup.id).document == doc
        assert empty == BuilderDocument(revision=doc.revision + 1)
        assert backup.document.tables[0].color == a.color and backup.document.folders == doc.folders
        assert backup.document.tables[0].columns == a.columns
        generated = save_canvas_work(store, w, expected_revision=empty.revision)
        assert generated.name != backup.name
        restored = load_builder_work(store, w, backup.id, expected_revision=empty.revision)
        assert restored.links == doc.links and restored.tables == doc.tables
    finally:
        store.close()


def test_downstream_trace_colors_branches_merges_cycles_and_joins():
    import shutil
    import subprocess

    from ui.builder_canvas import JS, TRACE_JS

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to exercise the canvas JavaScript traversal")
    check = r"""
const assert=require('node:assert/strict');
const doc={tables:[{id:'a',color:'#2563eb'},{id:'b',color:'#f97316'},{id:'merge'},{id:'end'},{id:'other'}],links:[
 {id:'am',source_table:'a',target_table:'merge'}, {id:'bm',source_table:'b',target_table:'merge'},
 {id:'me',source_table:'merge',target_table:'end'}, {id:'cycle',source_table:'end',target_table:'merge'},
 {id:'join',source_table:'a',target_table:'b',kind:'join'}]};
let trace=lineageTraces(doc,['a']);
assert.deepEqual([...trace.selected.tables].sort(),['a','end','merge']);
assert.deepEqual([...trace.selected.links].sort(),['am','cycle','join','me']);
assert.deepEqual([...trace.nodeColors.get('end')].sort(),['#2563eb','#f97316']);
assert.deepEqual([...trace.edgeColors.get('me')].sort(),['#2563eb','#f97316']);
assert.deepEqual([...trace.nodeColors.get('b')],['#f97316']);
assert.equal(trace.nodeColors.has('other'),false);
trace=lineageTraces(doc,['a','b']);assert.equal(trace.selected.tables.size,4);assert.equal(trace.selected.links.size,5);
trace=lineageTraces(doc,[]);assert.equal(trace.active,false);assert.equal(trace.edgeColors.get('me').size,2);
doc.tables[0].color='';doc.tables[1].color='';trace=lineageTraces(doc,['a']);
assert.equal(trace.edgeColors.size,0);assert.equal(trace.selected.tables.has('end'),true);
const paints=new Map(),defs={children:[]},svg={querySelector:()=>defs};
function node(tag,attributes,text,parent){const element={attributes:{...attributes},children:[],setAttribute(key,value){this.attributes[key]=value;}};if(parent)parent.children.push(element);return element;}
const gradientPaint=paint(['#2563eb','#f97316'],[0,10,100,10],'edge');
assert.equal(defs.children[0].attributes.gradientUnits,'userSpaceOnUse');
assert.equal(defs.children[0].attributes.y1,defs.children[0].attributes.y2);
assert.equal(paint(['#2563eb','#f97316'],[10,20,110,20],'edge'),gradientPaint);
assert.equal(paints.size,1);assert.equal(defs.children[0].attributes.x2,110);
paint(['#2563eb','#f97316'],[10,20,10,20],'edge');assert.notEqual(defs.children[0].attributes.x1,defs.children[0].attributes.x2);
let data={node_colors:{source:{fill:'#143e29'},intermediate:{fill:'#1a2d4f'},target:{fill:'#471e22'}}};
assert.ok(tint('#2563eb').match(/\d+/g).map(Number).every(channel=>channel<120));
data={node_colors:{source:{fill:'#e0efeb'},intermediate:{fill:'#ece7f7'},target:{fill:'#e3ecfb'}}};
assert.ok(tint('#2563eb').match(/\d+/g).map(Number).every(channel=>channel>140));
"""
    paint_js = JS[JS.index(" function paint("):JS.index("\n function arrow(")]
    tint_js = JS[JS.index(" function tint("):JS.index("\n s.expanded=")]
    subprocess.run([node, "-e", TRACE_JS + paint_js + tint_js + check], check=True, capture_output=True, text=True, timeout=10)
