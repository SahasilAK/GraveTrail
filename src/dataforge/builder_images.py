"""Fitted offline exports of authored table cards and column relationships."""
import math
from xml.etree import ElementTree as ET

from dataforge.builder_rendering import builder_html, builder_node_colors
from dataforge.configuration import VisualizationSettings
from dataforge.graph_images import (
    MAX_DIMENSION,
    MAX_PIXELS,
    MAX_SVG_BYTES,
    SVG_NS,
    _text,
    render_svg_png,
)
from dataforge.lineage_builder import BuilderDocument
from dataforge.theme_configuration import PALETTES, PRESETS


def export_builder_graph(document: BuilderDocument, format: str, appearance: VisualizationSettings,
                         theme: str | None = None) -> bytes:
    """Export the saved layout and relationship labels using the configured palette."""
    dark = PRESETS.get(theme, {}).get('base') == 'dark'
    colors = builder_node_colors(theme, appearance.graph_palette, dark=dark)
    if format == 'html':
        return builder_html(document, node_colors=colors)
    palette = PALETTES.get(theme, {})
    svg, width, height = _builder_svg(document, colors, palette.get('graph', '#15202e' if dark else '#ffffff'),
                                      palette.get('accent', '#9abcf0' if dark else '#176db1'))
    if format == 'svg':
        return svg
    if max(width, height) > MAX_DIMENSION or width * height > MAX_PIXELS:
        raise ValueError('PNG exceeds 8192 pixels per side or 16 million pixels. Use SVG or bring tables closer together')
    return render_svg_png(svg)


def _builder_svg(document: BuilderDocument, colors: dict, background: str, accent: str) -> tuple[bytes, int, int]:
    visible = [table for table in document.tables if table.position is not None]
    if not visible:
        raise ValueError('Place at least one table on the canvas before exporting an image')
    if any(abs(coordinate) > 10**9 for table in visible for coordinate in (table.position.x, table.position.y)):
        raise ValueError('Canvas coordinates exceed the image range')

    root = ET.Element('svg', {'xmlns': SVG_NS, 'font-family': 'DejaVu Sans, Arial, sans-serif'})

    def element(parent, tag, attrs, value=None):
        node = ET.SubElement(parent, tag, {k: str(v) for k, v in attrs.items()})
        if value is not None:
            node.text = _text(value)
        return node

    def label(parent, x, y, value, size, maximum, fill, **attrs):
        # The interactive canvas displays shortened labels and retains the full text on hover.
        if len(value) > maximum:
            short = value[:maximum - 1] + '…'
        else:
            short = value
        text = element(parent, 'text', {'x': x, 'y': y, 'fill': fill, 'font-size': size, **attrs}, short)
        element(text, 'title', {}, value)

    element(root, 'title', {}, 'GraveTrail authored lineage')
    background_rect = element(root, 'rect', {'fill': background})
    definitions = element(root, 'defs', {})
    arrow = element(definitions, 'marker', {'id': 'builder-arrow', 'viewBox': '0 0 8 8', 'refX': 7,
        'refY': 4, 'markerWidth': 8, 'markerHeight': 8, 'markerUnits': 'userSpaceOnUse', 'orient': 'auto'})
    element(arrow, 'path', {'d': 'M 2 1.5 L 6.5 4 L 2 6.5', 'fill': 'none', 'stroke': accent,
                           'stroke-width': 1.25, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'})
    relationships = element(root, 'g', {'fill': 'none'})
    endpoints, horizontal, vertical = {}, [], []

    for table in visible:
        x, y = table.position.x, table.position.y
        width = table.size.width if table.size else 420
        natural = 68 + max(30, 30 * len(table.columns))
        height = max(natural, table.size.height if table.size else 0)
        horizontal.extend((x, x + width))
        vertical.extend((y, y + height))
        scheme = colors[table.role]
        stroke = table.color or scheme['stroke']
        group = element(root, 'g', {'data-table': _text(table.id), 'transform': f'translate({x} {y})'})
        element(group, 'title', {}, table.name + (f' — {table.comment}' if table.comment else ''))
        element(group, 'rect', {'width': width, 'height': height, 'rx': 7, 'fill': scheme['fill'], 'stroke': stroke})
        element(group, 'rect', {'x': 0, 'y': 8, 'width': 4, 'height': 46, 'fill': stroke})
        label(group, 16, 25, table.name, 15, int((width - 32) / 8), scheme['text'], **{'font-weight': 600})
        info = f'{table.role} · {len(table.columns)} columns' + (f' · {table.system}' if table.system else '')
        label(group, 16, 47, info, 11, int((width - 32) / 6), scheme['text'])

        lines = element(group, 'g', {'stroke': scheme['stroke'], 'stroke-opacity': .4})
        element(lines, 'line', {'x1': 0, 'x2': width, 'y1': 62, 'y2': 62})
        for fraction in (.38, .64):
            element(lines, 'line', {'x1': width * fraction, 'x2': width * fraction, 'y1': 62, 'y2': height})
        if table.columns:
            row_height = 30 + (height - natural) / len(table.columns)
            for index, column in enumerate(table.columns):
                middle = 62 + (index + .5) * row_height
                endpoints[table.id, column.id] = (x, x + width, y + middle)
                for offset, fraction, value in ((12, .38, column.name), (width * .38 + 12, .26, column.data_type),
                                                (width * .64 + 10, .36, column.comment)):
                    label(group, offset, middle + 4, value, 12, max(3, int((width * fraction - 24) / 7)), scheme['text'])
                bottom = middle + row_height / 2
                element(lines, 'line', {'x1': 0, 'x2': width, 'y1': bottom, 'y2': bottom})

    for link in document.links:
        source = endpoints.get((link.source_table, link.source_column))
        target = endpoints.get((link.target_table, link.target_column))
        if source is None or target is None:
            continue
        join = link.kind == 'join'
        x1, y1 = source[1:]
        x2, y2 = target[1 if join else 0], target[2]
        bend = max(65, abs(x2 - x1) * .45)
        c1, c2 = (max(x1, x2) + 100,) * 2 if join else (x1 + bend, x2 - bend)
        horizontal.extend((c1, c2, max(x1, x2) + 330 if join else (x1 + x2) / 2))
        path = element(relationships, 'path', {'d': f'M{x1},{y1} C{c1},{y1} {c2},{y2} {x2},{y2}',
            'data-link': _text(link.id), 'stroke': '#d89e3a' if join else accent, 'stroke-width': 1.5,
            'stroke-linecap': 'round', **({'stroke-dasharray': '6 4'} if join else {'marker-end': 'url(#builder-arrow)'})})
        title = link.join_type + (f' · {link.label}' if link.label else '') if join else link.label
        element(path, 'title', {}, title)
        if title:
            label(relationships, max(x1, x2) + 90 if join else (x1 + x2) / 2, (y1 + y2) / 2 - 10,
                  title, 12, 40, colors['source']['text'], **{'text-anchor': 'start' if join else 'middle'})

    x, y = min(horizontal) - 40, min(vertical) - 40
    width, height = math.ceil(max(horizontal) + 40 - x), math.ceil(max(vertical) + 40 - y)
    root.attrib.update({'viewBox': f'{x} {y} {width} {height}', 'width': str(width), 'height': str(height)})
    background_rect.attrib.update({'x': str(x), 'y': str(y), 'width': str(width), 'height': str(height)})
    svg = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    if len(svg) > MAX_SVG_BYTES:
        raise ValueError('SVG exceeds 4 MiB. Narrow the canvas selection')
    return svg, width, height
