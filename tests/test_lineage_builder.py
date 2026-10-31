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
    next(t for t in app.text_input if t.label == "Table name").set_value("new_table")
    next(b for b in app.button if b.label == "Create table").click().run()
    assert not app.exception
    store = get_store(str(tmp_path))
    assert load_builder(store, app.session_state["workspace"]).tables[0].name == "new_table"
    app.segmented_control[0].set_value("Build lineage").run()
    assert not app.exception
    next(c for c in app.selectbox if c.label == "Builder export format").set_value("HTML").run()
    next(b for b in app.button if b.label == "Prepare builder export").click().run()
    assert not app.exception
    assert len(app.get("download_button")) == 1
