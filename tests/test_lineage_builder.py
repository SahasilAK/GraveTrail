import io
import zipfile

import pytest
from pydantic import ValidationError


def test_builder_persistence_links_and_exports(tmp_path):
    from dataforge.lineage_builder import (
        BuilderDocument,
        BuilderLink,
        BuilderTable,
        delete_builder_tables,
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
        retained = save_builder(store, workspace, BuilderDocument(revision=saved.revision))
        assert {t.name for t in retained.tables} == {a.name, b.name}
        assert all(t.position is None and t.catalog_hidden for t in retained.tables)
        with pytest.raises(ValueError, match="changed"):
            delete_builder_tables(store, workspace, [a.id], expected_revision=saved.revision)
        deleted = delete_builder_tables(store, workspace, [a.id], expected_revision=retained.revision)
        assert [t.id for t in deleted.tables] == [b.id]
    finally:
        store.close()


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
        BuilderWorkExistsError,
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
        doc.tables[0].position.x = 80
        doc = save_builder(store, w, doc)
        updated = save_canvas_work(store, w, "My design", work_id=named.id, expected_revision=doc.revision)
        assert updated.id == named.id and updated.document == doc
        assert len(list_builder_works(store, w)) == 1
        with pytest.raises(BuilderWorkExistsError, match="name|exists") as duplicate:
            save_canvas_work(store, w, "  MY DESIGN  ", expected_revision=doc.revision, clear=True)
        assert duplicate.value.work.id == named.id and duplicate.value.work.name == "My design"
        with pytest.raises(ValueError, match="changed"):
            save_canvas_work(store, w, expected_revision=0, clear=True)
        assert load_builder(store, w) == doc and len(list_builder_works(store, w)) == 1
        doc.tables[0].position.x = 90
        doc = save_builder(store, w, doc)
        original_set = store.set_setting

        def fail_clear(workspace, key, value):
            if key == "lineage_builder":
                raise OSError("Storage unavailable")
            original_set(workspace, key, value)

        with monkeypatch.context() as patch:
            patch.setattr(store, "set_setting", fail_clear)
            with pytest.raises(OSError):
                save_canvas_work(store, w, "My design", work_id=named.id, expected_revision=doc.revision, clear=True)
        assert load_builder(store, w) == doc and len(list_builder_works(store, w)) == 1
        assert get_builder_work(store, w, named.id).document == updated.document
        backup = save_canvas_work(store, w, "My design", work_id=named.id, expected_revision=doc.revision, clear=True)
        assert backup.id == named.id and len(list_builder_works(store, w)) == 1
        empty = load_builder(store, w)
        assert get_builder_work(store, w, backup.id).document == doc
        assert empty.revision == doc.revision + 1 and not empty.links and not empty.folders
        assert [t.name for t in empty.tables] == [t.name for t in doc.tables]
        assert all(t.position is None and t.folder is None and t.catalog_hidden for t in empty.tables)
        assert backup.document.tables[0].color == a.color and backup.document.folders == doc.folders
        assert backup.document.tables[0].columns == a.columns
        generated = save_canvas_work(store, w, expected_revision=empty.revision)
        assert generated.name != backup.name
        new_table = BuilderTable(name="new_design_table", canvas_member=True)
        empty.tables.append(new_table)
        current = save_builder(store, w, empty)
        restored = load_builder_work(store, w, backup.id, expected_revision=current.revision)
        assert restored.links == doc.links and restored.tables[:2] == doc.tables
        assert restored.tables[2].id == new_table.id and restored.tables[2].catalog_hidden
    finally:
        store.close()
