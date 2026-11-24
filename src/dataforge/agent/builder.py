"""Authorized workspace operations for authored lineage documents and snapshots."""
import hashlib
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from dataforge.agent.contracts import AgentError, QueryOptions, compact
from dataforge.artifacts import write_artifact
from dataforge.lineage_builder import (
    BuilderDocument,
    BuilderTable,
    BuilderWork,
    BuilderWorkExistsError,
    delete_builder_tables,
    export_schemas,
    export_tabular,
    get_builder_work,
    list_builder_works,
    load_builder,
    load_builder_work,
    save_builder,
    save_builder_work,
    save_canvas_work,
    schema_rows,
)
from dataforge.schema_imports import import_schema

BuilderView = Literal['tables', 'columns', 'links', 'folders', 'works']
BuilderFormat = Literal['json', 'yaml', 'sql', 'csv', 'xlsx', 'html', 'svg', 'png']
BuilderRole = Literal['source', 'intermediate', 'target']
BuilderKind = Literal['document', 'schemas']
READS = {'builder_inspect', 'builder_schema_preview', 'builder_delete_preview'}
WRITES = {'builder_apply', 'builder_work_save', 'builder_work_load', 'builder_work_import',
          'builder_schema_import', 'builder_export', 'builder_delete', 'source_dialect_update'}
SOURCE_ACTIONS = READS | (WRITES - {'source_dialect_update'})
SCHEMA_FORMATS = {'json', 'yaml', 'sql', 'csv', 'xlsx'}
DOCUMENT_FORMATS = {'json', 'html', 'svg', 'png', 'xlsx', 'csv'}
SCHEMA_EXTENSIONS = {'.sql', '.ddl', '.hql', '.sas', '.yml', '.yaml', '.json', '.xml', '.csv', '.tsv'}
MIB = 1024 * 1024


def _revision(document: BuilderDocument, expected: int) -> None:
    if type(expected) is not int or expected != document.revision:
        raise AgentError('conflict', 'The builder changed in another session. Inspect its current revision and retry.')


def _document_result(document: BuilderDocument) -> dict[str, Any]:
    return {'revision': document.revision, 'table_count': len(document.tables),
            'link_count': len(document.links), 'folder_count': len(document.folders)}


def _work_result(work: BuilderWork, revision: int) -> dict[str, Any]:
    return {'work_id': work.id, 'name': work.name, 'updated_at': work.updated_at,
            'work_revision': work.document.revision, 'revision': revision}


class BuilderOperations:
    """Connect CLI and MCP authoring to the UI's existing Builder persistence and validation."""

    def _builder_inspect(self, w: str, opts: QueryOptions, view: BuilderView = 'tables',
                         work_id: str = '', table_id: str = '') -> dict[str, Any]:
        document = get_builder_work(self.store, w, work_id).document if work_id else load_builder(self.store, w)
        if table_id and (view not in {'tables', 'columns'} or table_id not in {t.id for t in document.tables}):
            raise AgentError('not_found', 'Select an existing table ID in the tables or columns view')
        tables = [t for t in document.tables if not table_id or t.id == table_id]
        if view == 'tables':
            items = [{**t.model_dump(exclude={'columns'}), 'column_count': len(t.columns)} for t in tables]
        elif view == 'columns':
            items = [{**column.model_dump(), 'table_id': table.id} for table in tables for column in table.columns]
        elif view == 'links':
            items = [link.model_dump() for link in document.links]
        elif view == 'folders':
            items = [folder.model_dump() for folder in document.folders]
        elif view == 'works' and not work_id:
            items = [work.model_dump() for work in list_builder_works(self.store, w)]
        else:
            raise AgentError('validation_failed', 'Choose tables, columns, links, folders or the workspace works list')
        return self._page(w, opts, ['builder_inspect', view, work_id, table_id, document.revision],
                          items, work_id=work_id, view=view, **_document_result(document))

    def _builder_file(self, value: str, extensions: set[str], limit: int) -> tuple[Path, bytes]:
        path = self.policy.import_path(value)
        if not path.is_file() or path.suffix.lower() not in extensions:
            raise AgentError('invalid_path', 'Choose an approved regular file with a supported extension')
        with path.open('rb') as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise AgentError('resource_limit', 'Builder import exceeds its file or batch byte limit')
        return path, data

    def _builder_input(self, document: dict | None, path: str, limit: int) -> BuilderDocument:
        if (document is None) == (not path):
            raise AgentError('validation_failed', 'Provide either a Builder document or an approved JSON path')
        if path:
            _, data = self._builder_file(path, {'.json'}, limit)
            return BuilderDocument.model_validate_json(data)
        if len(compact(document).encode()) > limit:
            raise AgentError('resource_limit', 'Builder document exceeds its byte limit')
        return BuilderDocument.model_validate(document)

    def _builder_apply(self, w: str, opts: QueryOptions, expected_revision: int,
                       document: dict | None = None, path: str = '') -> dict[str, Any]:
        _revision(load_builder(self.store, w), expected_revision)
        incoming = self._builder_input(document, path, 64 * MIB)
        incoming.revision = expected_revision
        return _document_result(save_builder(self.store, w, incoming))

    def _builder_work_save(self, w: str, opts: QueryOptions, expected_revision: int, name: str = '',
                           clear: bool = False, work_id: str = '') -> dict[str, Any]:
        _revision(load_builder(self.store, w), expected_revision)
        if work_id and not name:
            name = get_builder_work(self.store, w, work_id).name
        try:
            work = save_canvas_work(self.store, w, name, expected_revision=expected_revision,
                                    clear=clear, work_id=work_id or None)
        except BuilderWorkExistsError as exc:
            raise AgentError('conflict', str(exc), work_id=exc.work.id) from None
        return _work_result(work, load_builder(self.store, w).revision)

    def _builder_work_load(self, w: str, opts: QueryOptions, expected_revision: int,
                           work_id: str) -> dict[str, Any]:
        _revision(load_builder(self.store, w), expected_revision)
        return _document_result(load_builder_work(self.store, w, work_id, expected_revision=expected_revision))

    def _builder_work_import(self, w: str, opts: QueryOptions, name: str,
                             document: dict | None = None, path: str = '') -> dict[str, Any]:
        incoming = self._builder_input(document, path, 64 * MIB)
        try:
            work = save_builder_work(self.store, w, name, document=incoming)
        except BuilderWorkExistsError as exc:
            raise AgentError('conflict', str(exc), work_id=exc.work.id) from None
        return _work_result(work, load_builder(self.store, w).revision)

    def _builder_schemas(self, w: str, paths: list[str],
                         dialect: str | None) -> tuple[BuilderDocument, list[BuilderTable], list[str], str]:
        if not 1 <= len(paths) <= 100:
            raise AgentError('validation_failed', 'Select between 1 and 100 schema files')
        from dataforge.configuration import ParsingSettings

        if dialect is not None:
            ParsingSettings(dialect=dialect)
        document = load_builder(self.store, w)
        files, notes, tables, total = [], [], [], 0
        for value in paths:
            path, data = self._builder_file(value, SCHEMA_EXTENSIONS, min(5 * MIB, 10 * MIB - total))
            total += len(data)
            files.append([path.name, hashlib.sha256(data).hexdigest()])
            found, warnings = import_schema(path.name, data, dialect or None)
            notes.extend(f'{path.name}: {warning}'[:400] for warning in warnings)
            for table in found:
                columns = [column.model_copy(update={'id': uuid4().hex}) for column in table.columns]
                tables.append(table.model_copy(update={'id': uuid4().hex, 'columns': columns, 'position': None,
                    'canvas_member': False, 'catalog_hidden': False, 'folder': None, 'size': None, 'color': ''}))
        combined = BuilderDocument(revision=document.revision, tables=document.tables + tables,
                                   links=document.links, folders=document.folders)
        pin = hashlib.sha256(compact([w, document.revision, dialect, files]).encode()).hexdigest()
        return combined, tables, notes, pin

    def _builder_schema_preview(self, w: str, opts: QueryOptions, paths: list[str],
                                dialect: str | None = None) -> dict[str, Any]:
        document, tables, notes, pin = self._builder_schemas(w, paths, dialect)
        rows = [{'kind': 'warning', 'message': note} for note in notes]
        rows.extend({'kind': 'schema', **row} for row in schema_rows(BuilderDocument(tables=tables)))
        return self._page(w, opts, ['builder_schema_preview', pin], rows, pin=pin,
                          revision=document.revision, table_count=len(tables), warnings=len(notes))

    def _builder_schema_import(self, w: str, opts: QueryOptions, paths: list[str], expected_pin: str,
                               dialect: str | None = None) -> dict[str, Any]:
        document, tables, _, pin = self._builder_schemas(w, paths, dialect)
        if pin != expected_pin:
            raise AgentError('conflict', 'The Builder or schema files changed. Preview the import again.')
        if not tables:
            raise AgentError('validation_failed', 'No table definitions were found in the selected files')
        return {**_document_result(save_builder(self.store, w, document)), 'imported_tables': len(tables)}

    def _builder_export(self, w: str, opts: QueryOptions, kind: BuilderKind = 'document',
                        format: BuilderFormat = 'json', work_id: str = '',
                        table_ids: list[str] | None = None, role: BuilderRole | None = None) -> dict[str, Any]:
        document = get_builder_work(self.store, w, work_id).document if work_id else load_builder(self.store, w)
        if kind == 'schemas' and format in SCHEMA_FORMATS:
            if table_ids is not None and (not table_ids or not set(table_ids) <= {t.id for t in document.tables}):
                raise AgentError('validation_failed', 'Choose existing table IDs for the schema export')
            data = export_schemas(document, format, table_ids=table_ids, role=role)
        elif kind == 'document' and format in DOCUMENT_FORMATS and table_ids is None and role is None:
            if format == 'json':
                data = document.model_dump_json(indent=2).encode()
            elif format in {'csv', 'xlsx'}:
                data = export_tabular(document, format)
            else:
                from dataforge.builder_images import export_builder_graph
                from dataforge.configuration import VisualizationSettings
                from dataforge.theme_configuration import current_preset

                theme = current_preset(self.theme_config_path) if self.theme_config_path.is_file() else None
                data = export_builder_graph(document, format, VisualizationSettings.from_store(self.store, w), theme)
        else:
            raise AgentError('validation_failed', 'Choose a supported Builder export format and scope')
        filename = f'{"table-schemas" if kind == "schemas" else "lineage-builder"}.{format}'
        written = write_artifact(self.store, w, f'builder-{kind}', format, data, True, {}, True)
        return {**written, 'filename': filename, 'revision': document.revision, 'work_id': work_id}

    def _builder_delete_preview(self, w: str, opts: QueryOptions, table_ids: list[str]) -> dict[str, Any]:
        document = load_builder(self.store, w)
        ids = set(table_ids)
        tables = [t for t in document.tables if t.id in ids]
        if not ids or ids != {t.id for t in tables}:
            raise AgentError('validation_failed', 'Select existing workspace table IDs to delete')
        affected = sum(e.source_table in ids or e.target_table in ids for e in document.links)
        return self._page(w, opts, ['builder_delete_preview', document.revision, sorted(ids)],
                          [{'id': t.id, 'name': t.name} for t in tables], revision=document.revision,
                          affected_tables=len(tables), affected_links=affected)

    def _builder_delete(self, w: str, opts: QueryOptions, table_ids: list[str],
                        expected_revision: int, confirm: str) -> dict[str, Any]:
        self.policy.require('admin')
        if confirm != 'DELETE BUILDER TABLES':
            raise AgentError('validation_failed', 'Confirm with DELETE BUILDER TABLES after inspecting the deletion preview')
        _revision(load_builder(self.store, w), expected_revision)
        return _document_result(delete_builder_tables(self.store, w, table_ids, expected_revision=expected_revision))

    def _source_dialect_update(self, w: str, opts: QueryOptions, file_id: str,
                               sql_dialect: str | None = None) -> dict[str, Any]:
        from dataforge.configuration import ParsingSettings
        from dataforge.services import set_source_dialect, source_dialect

        set_source_dialect(self.store, w, file_id, sql_dialect)
        row = self.store.file(file_id)
        return {'file_id': file_id, 'sql_dialect_override': sql_dialect,
                'sql_dialect': source_dialect(row, ParsingSettings.from_store(self.store, w).model_dump()),
                'parsing_status': row['parsing_status']}
