"""Compatibility route for existing transformation-lineage bookmarks."""
from ui.column_lineage import render_column_lineage
from ui.common import choose_asset, context, load_graph, title

title("Transformation lineage", "Follow how a column is produced, or which outputs depend on it.")
store, w = context()
asset = choose_asset(load_graph(store, w), "transformations")
if asset:
    render_column_lineage(store, w, asset)
