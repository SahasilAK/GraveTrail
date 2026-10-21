"""Inert, fitted graph images from the browser's scene. No source text or resources."""
from __future__ import annotations

import re
import subprocess
import sys
import threading
from typing import Any, Literal
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field

from dataforge.configuration import VisualizationSettings
from dataforge.exports import graph_data
from dataforge.graph import LineageGraph

MAX_NODES, MAX_EDGES = 1000, 5000
MAX_DIMENSION, MAX_PIXELS = 8192, 16_000_000
MAX_SVG_BYTES, MAX_PNG_BYTES, MAX_SECONDS = 4 * 1024**2, 16 * 1024**2, 15
SVG_NS = 'http://www.w3.org/2000/svg'
RENDER_SLOTS = threading.BoundedSemaphore(2)


class ImageOptions(BaseModel):
    """Bounded rendering options accepted by SVG and PNG graph export."""

    model_config = ConfigDict(extra='forbid', strict=True)
    scale: Literal[1, 2] = 1
    background: Literal['light', 'dark', 'transparent'] = 'light'
    title: str = Field(default='GraveTrail lineage', max_length=200)
    legend: bool = True


def png_available() -> bool:
    """Check whether the optional PNG renderer can be imported."""
    try:
        import resvg_py  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


def safe_image_filename(workspace: str, asset: str, format: str) -> str:
    """Create a filesystem-safe image filename from workspace and asset labels."""

    def safe(value: str) -> str:
        """Normalize a label to a bounded filename component."""
        return re.sub(r'[^\w.-]+', '-', str(value), flags=re.UNICODE).strip('.-')[:70] or 'graph'
    return f'gravetrail-{safe(workspace)}-{safe(asset)}.{format}'


def _text(value: object) -> str:
    """Remove characters forbidden by XML 1.0 from text content."""
    # XML 1.0 excludes control characters and lone surrogates even inside escaped text.
    return ''.join(c for c in str(value) if c in '\t\n\r' or
                   0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF)


def render_graph_image(
    graph: LineageGraph,
    *,
    format: str = 'svg',
    appearance: VisualizationSettings | None = None,
    options: ImageOptions | dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Render a fitted graph as SVG or PNG and return bounded image metadata.

    Args:
        graph: Filtered graph to render.
        format: Requested image format, either ``svg`` or ``png``.
        appearance: Graph label, palette, and edge-width settings.
        options: Validated image title, scale, background, and legend options.
        scope: Optional selection and completeness metadata shown with the image.

    Returns:
        Rendered image bytes and metadata describing dimensions, counts, and warnings.

    Raises:
        ValueError: If the graph or output exceeds a rendering limit or PNG rendering fails.
    """
    if format not in {'svg', 'png'}:
        raise ValueError('Choose SVG or PNG')
    options = options if isinstance(options, ImageOptions) else ImageOptions.model_validate(options or {})
    if not graph.nodes:
        raise ValueError('The graph has no nodes; select an asset or analyze sources first')
    if len(graph.nodes) > MAX_NODES or len(graph.graph.edges) > MAX_EDGES:
        raise ValueError('Image limit is 1000 nodes and 5000 relationships; narrow the graph or reduce depth')
    if sum(len(str(n.get('name', ''))) for n in graph.nodes.values()) > 500_000:
        raise ValueError('Image label budget exceeded; narrow the graph')
    appearance = appearance or VisualizationSettings()
    scene = graph_data(graph, appearance)
    x, y, width, height = scene['bounds']
    width = max(width, 780)
    scope = scope or {}
    warnings = list(scope.get('warnings', []))
    if graph.truncated and not any('boundary' in w.lower() for w in warnings):
        warnings.append('Depth/node boundary or missing asset metadata: this graph is incomplete.')
    lines = [options.title] if options.title else []
    lines += [str(scope[key]) for key in ('selection', 'filters', 'temporary_policy') if scope.get(key)]
    lines += warnings
    # Hard wrapping also handles imported identifiers without whitespace.
    columns = (width - 40) // 14
    lines = [part[i:i+columns] for line in lines for part in _text(line).splitlines()
             for i in range(0, len(part), columns)]
    if len(lines) > 50:
        raise ValueError('Image annotation budget exceeded; shorten the title or selection')
    header = 24 + 20 * len(lines)
    footer = 56 if options.legend else 16
    height += header + footer
    pixel_width, pixel_height = width * options.scale, height * options.scale
    if format == 'png' and (max(pixel_width, pixel_height) > MAX_DIMENSION or pixel_width * pixel_height > MAX_PIXELS):
        raise ValueError('PNG exceeds 8192 pixels per side or 16 million pixels; use scale 1, reduce depth or export SVG')
    dark = options.background == 'dark'
    text, border, edge = ('#edf2f9', '#7489a3', '#a8bdd2') if dark else ('#23334a', '#8d9cb1', '#607b96')
    fills = (['#303b48', '#4c3823', '#3b3354', '#203f3d', '#273d58'] if dark else
             ['#edf0f4', '#fff0d4', '#ece7f7', '#e0efeb', '#e3ecfb'])
    def add(
        parent: ET.Element,
        tag: str,
        attrs: dict[str, Any] | None = None,
        value: object | None = None,
    ) -> ET.Element:
        """Append a safely escaped SVG element and optional text to its parent."""
        node = ET.SubElement(parent, tag, {k: str(v) for k, v in (attrs or {}).items()})
        if value is not None:
            node.text = _text(value)
        return node
    root = ET.Element('svg', {'xmlns': SVG_NS, 'width': str(pixel_width), 'height': str(pixel_height),
        'viewBox': f'0 0 {width} {height}', 'font-family': 'DejaVu Sans, Arial, sans-serif', 'font-size': '13'})
    add(root, 'title', value=options.title)
    add(root, 'desc', value='Entire filtered graph; independent of browser pan/zoom. Logical dependencies, not execution order.')
    if options.background != 'transparent':
        add(root, 'rect', {'width': width, 'height': height, 'fill': '#171e29' if dark else '#ffffff'})
    for i, line in enumerate(lines):
        add(root, 'text', {'x': 20, 'y': 24 + i * 20, 'fill': text}, line)
    defs = add(root, 'defs')
    marker = add(defs, 'marker', {'id': 'df-arrow', 'viewBox': '0 0 10 10', 'refX': 9, 'refY': 5,
        'markerWidth': 7, 'markerHeight': 7, 'orient': 'auto-start-reverse'})
    add(marker, 'path', {'d': 'M 0 0 L 10 5 L 0 10 z', 'fill': edge})
    stage = add(root, 'g', {'transform': f'translate({-x},{header-y})'})
    for i, e in enumerate(scene['edges']):
        add(stage, 'path', {'d': e['path'], 'data-edge': i, 'fill': 'none', 'stroke': edge,
            'stroke-width': appearance.graph_edge_width, 'marker-end': 'url(#df-arrow)'})
    for n in scene['nodes']:
        label = n['name'] + (f" [job: {n['job_id']}]" if n.get('job_id') and n['job_id'] != 'workspace' else '')
        group = add(stage, 'g', {'data-node': n['asset_id'], 'transform': f"translate({n['x']},{n['y']})"})
        color = fills[0 if appearance.graph_palette == 'neutral' else 1 if n.get('kind') == 'unresolved' else
                      2 if n.get('temporary') else 3 if n.get('source') else 4]
        add(group, 'title', value=label)
        add(group, 'rect', {'width': n['width'], 'height': 48, 'rx': 9, 'fill': color, 'stroke': border})
        if appearance.graph_labels != 'hidden':
            visible = label[:21] + '…' if appearance.graph_labels == 'compact' and len(label) > 22 else label
            attrs = {'x': 12, 'y': 29, 'fill': text}
            if len(visible) * 8 > n['width'] - 52:
                attrs.update(textLength=n['width'] - 52, lengthAdjust='spacingAndGlyphs')
            add(group, 'text', attrs, visible)
    if options.legend:
        for i, label in enumerate(['Neutral', 'Unresolved', 'Temporary', 'Source', 'Table']):
            position = 20 + i * 148
            add(root, 'rect', {'x': position, 'y': height-36, 'width': 16, 'height': 16,
                'rx': 3, 'fill': fills[0 if appearance.graph_palette == 'neutral' else i], 'stroke': border})
            add(root, 'text', {'x': position+22, 'y': height-23, 'fill': text}, label)
    svg = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    if len(svg) > MAX_SVG_BYTES:
        raise ValueError('SVG exceeds 4 MiB; narrow the graph')
    metadata = {'node_count': len(scene['nodes']), 'edge_count': len(scene['edges']),
        'width': pixel_width, 'height': pixel_height, 'warnings': warnings,
        'mime_type': 'image/svg+xml' if format == 'svg' else 'image/png'}
    if format == 'svg':
        return svg, metadata
    if not png_available():
        raise ValueError('PNG renderer unavailable; install resvg-py or download SVG instead')
    command = ([sys.executable, '--render-graph-image'] if getattr(sys, 'frozen', False) else
               [sys.executable, '-m', 'dataforge.image_worker'])
    if not RENDER_SLOTS.acquire(blocking=False):
        raise ValueError('PNG renderer is busy (two active jobs); retry shortly or download SVG')
    try:
        try:
            result = subprocess.run(command, input=svg, capture_output=True, timeout=MAX_SECONDS,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        except subprocess.TimeoutExpired:
            raise ValueError('PNG render time limit (15 seconds) exceeded; narrow the graph or download SVG') from None
    finally:
        RENDER_SLOTS.release()
    if result.returncode or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('PNG rendering failed; check the renderer installation or download SVG')
    if len(result.stdout) > MAX_PNG_BYTES:
        raise ValueError('PNG exceeds 16 MiB; reduce scale or narrow the graph')
    return result.stdout, metadata
