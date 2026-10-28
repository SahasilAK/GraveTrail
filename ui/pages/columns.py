"""Direct references and interactive column lineage."""
import streamlit as st

from ui.column_lineage import render_column_lineage
from ui.column_references import render_column_references
from ui.common import choose_asset, context, load_graph, title

title("Columns", "Inspect direct references or follow how column values flow.")
store, w = context()
asset = choose_asset(load_graph(store, w), "columns")
if asset:
    view = st.segmented_control("Columns view", ["Direct references", "Lineage graph"], default="Direct references", key="columns_view")
    if view == "Lineage graph":
        render_column_lineage(store, w, asset)
    else:
        render_column_references(store, w, asset)
