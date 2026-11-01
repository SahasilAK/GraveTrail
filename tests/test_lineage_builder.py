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
