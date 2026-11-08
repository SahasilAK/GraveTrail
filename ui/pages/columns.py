"""Direct references and interactive column lineage."""
import streamlit as st

from ui.column_lineage import render_column_lineage
from ui.column_references import render_column_references
from ui.common import choose_asset, context, load_graph, title

title("Columns", "Follow how column values flow or inspect direct references.")
store, w = context()
asset = choose_asset(load_graph(store, w), "columns")
if asset:
    view = st.segmented_control("Columns view", ["Lineage graph", "Direct references"], default="Lineage graph", key="columns_view")
    if view == "Lineage graph":
        render_column_lineage(store, w, asset)
    else:
        render_column_references(store, w, asset)
