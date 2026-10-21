"""Snapshot and disclose the same filtered graph for UI and automation images."""
import hashlib
import json
from typing import Any

from dataforge.configuration import VisualizationSettings
from dataforge.graph import LineageGraph
from dataforge.graph_images import render_graph_image, safe_image_filename
from dataforge.store import Store


def export_graph_image(
    store: Store,
    workspace: str,
    asset: str = '',
    *,
    direction: str = 'upstream',
    max_depth: int = 15,
    max_nodes: int = 2000,
    collapse_temporary: bool | None = None,
    format: str = 'svg',
    options: Any = None,
    appearance: VisualizationSettings | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Render a filtered workspace graph and return its image and scope summary.

    Args:
        store: Workspace store used to load graph data and settings.
        workspace: Workspace identifier to render.
        asset: Optional exact asset ID to focus the graph on.
        direction: Traversal direction when an asset is selected.
        max_depth: Maximum traversal depth for a focused graph.
        max_nodes: Maximum number of graph nodes to include.
        collapse_temporary: Whether temporary assets are collapsed; defaults to appearance settings.
        format: Image format passed to the renderer.
        options: Optional renderer-specific image options.
        appearance: Optional visualization settings; defaults to stored settings.

    Returns:
        Image bytes and metadata describing the rendered scope and completeness.

    Raises:
        ValueError: If the selection, graph bounds, or direction are invalid.
    """
    from dataforge.services import analysis_is_current

    if direction not in {'upstream', 'downstream', 'combined'}:
        raise ValueError('Use upstream, downstream or combined direction')
    if type(max_depth) is not int or not 1 <= max_depth <= 30 or type(max_nodes) is not int or not 1 <= max_nodes <= 20000:
        raise ValueError('Use depth 1–30 and node limit 1–20000')
    with store.lock:
        workspaces = store.rows('SELECT name FROM workspaces WHERE workspace_id=?', [workspace])
        if not workspaces:
            raise ValueError('Select an existing workspace')
        assets = store.rows('SELECT * FROM assets WHERE workspace_id=? ORDER BY name LIMIT 20001', [workspace])
        edge_count = store.rows('SELECT count(*) AS n FROM edges WHERE workspace_id=?', [workspace])[0]['n']
        if len(assets) > 20000 or edge_count > 100000:
            raise ValueError('Workspace graph limit is 20000 assets and 100000 evidence edges; narrow the workspace')
        if asset and not any(a['asset_id'] == asset for a in assets):
            raise ValueError('Select an existing exact asset ID')
        edges = store.rows('SELECT edge_id,source_id,target_id,confidence,status FROM edges WHERE workspace_id=? ORDER BY edge_id', [workspace])
        confidence = store.setting(workspace, 'min_lineage_confidence', 0.)
        inferred = store.setting(workspace, 'include_inferred', True)
        appearance = appearance or VisualizationSettings.from_store(store, workspace)
        collapse = appearance.collapse_temporary if collapse_temporary is None else collapse_temporary
        revisions = store.rows("SELECT run_id FROM analysis_runs WHERE workspace_id=? AND status='completed' ORDER BY created_at DESC LIMIT 1", [workspace])
        current = analysis_is_current(store, workspace)
        diagnostics = store.rows("SELECT count(*) AS n FROM diagnostics WHERE workspace_id=? AND severity IN ('warning','error')", [workspace])[0]['n']
    graph = LineageGraph(assets, edges, confidence, inferred)
    if collapse:
        graph = graph.simplified(keep=[asset], evidence_limit=20000)
    if asset:
        graph = graph.focus(asset, direction, max_depth, max_nodes)
    elif len(graph.nodes) > max_nodes:
        raise ValueError('Graph exceeds the selected node limit; choose an exact asset or increase the limit')
    selected = graph.nodes[asset]['name'] if asset else 'All filtered assets'
    warnings = []
    if graph.truncated:
        warnings.append(f'Depth/node boundary (depth {max_depth}, node limit {max_nodes}) or missing metadata; graph is incomplete.')
    if graph.unresolved_edges:
        warnings.append('Unresolved evidence is a traversal boundary; this graph is incomplete.')
    if confidence > 0 or not inferred:
        warnings.append('Status/confidence filters limit represented relationships.')
    if collapse:
        warnings.append('Temporary steps are collapsed where safe; intermediate assets may be omitted.')
    if not current:
        warnings.append('Analysis is not current; pending changes are not represented.')
    if diagnostics:
        warnings.append(f'{diagnostics} analysis warnings/errors; unsupported coverage may remain.')
    revision = revisions[0]['run_id'] if revisions else 'unanalysed'
    scope = {'selection': f'{selected} · {direction if asset else "all directions"} · depth {max_depth} · node limit {max_nodes}',
        'filters': f'minimum confidence {confidence:g}; inferred {"included" if inferred else "excluded"}',
        'temporary_policy': 'Temporary steps collapsed' if collapse else 'Temporary steps included', 'warnings': warnings}
    data, summary = render_graph_image(graph, format=format, appearance=appearance, options=options, scope=scope)
    graph_revision = hashlib.sha256(json.dumps([revision, assets, edges, scope, appearance.model_dump()],
                                              default=str, sort_keys=True).encode()).hexdigest()
    return data, {**summary, 'revision': revision, 'graph_revision': graph_revision,
        'complete': current and not graph.truncated and not graph.unresolved_edges and not diagnostics,
        'coverage': {'scope': 'entire_filtered_graph', 'direction': direction if asset else 'all',
            'max_depth': max_depth, 'max_nodes': max_nodes, 'minimum_confidence': confidence,
            'include_inferred': inferred, 'collapse_temporary': collapse, 'truncated': graph.truncated,
            'analysis_current': current},
        'filename': safe_image_filename(workspaces[0]['name'], selected, format)}
