"""Streamlit adapters for the shared authored lineage canvas."""
import streamlit as st

from dataforge.builder_rendering import BODY, COLUMN_BODY, COLUMN_JS, CSS, JS
from dataforge.builder_rendering import builder_html as builder_html
from dataforge.builder_rendering import builder_node_colors as builder_node_colors
from dataforge.datatypes import TYPE_CATALOG
from dataforge.lineage_builder import BuilderDocument

_CANVAS = st.components.v2.component("dataforge_lineage_builder", html=BODY, css=CSS,
    js=JS + "\nexport default function(c){return mountBuilder(c.parentElement,c.data,v=>c.setTriggerValue('edit',v),v=>c.setTriggerValue('create_table',v),v=>c.setTriggerValue('work_action',v));}\n")

_COLUMN_EDITOR = st.components.v2.component("dataforge_schema_columns", html='<div class="lb-root">'+COLUMN_BODY+'</div>',
    css=CSS, js=COLUMN_JS + "\nexport default function(c){mountColumns(c.parentElement.querySelector('.lb-columns'),c.data.rows,c.data.options,v=>c.setStateValue('rows',v));}\n")


def column_editor(rows: list[dict], system: str, key: str) -> list[dict]:
    """Use the canvas's type-or-choose column fields inside the native table form."""
    result = _COLUMN_EDITOR(data={"rows": rows, "options": TYPE_CATALOG.get(system, TYPE_CATALOG["Generic SQL"])},
                            default={"rows": rows}, key=key, on_rows_change=lambda: None, height="content")
    return result.rows


def canvas(document: BuilderDocument, key: str, on_edit, error: str = "", on_create=None, node_colors: dict | None = None,
           on_work=None, work_result: dict | None = None, current_work: dict | None = None, work_conflict: dict | None = None):
    return _CANVAS(data={"document": document.model_dump(), "error": error, "type_catalog": TYPE_CATALOG,
                         "node_colors": node_colors or builder_node_colors(None), "work_result": work_result,
                         "current_work": current_work, "work_conflict": work_conflict}, key=key,
                   on_edit_change=on_edit, on_create_table_change=on_create or (lambda: None),
                   on_work_action_change=on_work or (lambda: None), height="content")
