"""Static exports retain the UI scene while excluding source and active content."""
import struct
from xml.etree import ElementTree as ET

import pytest

from dataforge import graph_images as images
from dataforge.configuration import VisualizationSettings
from dataforge.exports import graph_data
from dataforge.graph import LineageGraph

NS = {'s': 'http://www.w3.org/2000/svg'}


def graph():
    names = ['日本語_' + 'long_' * 60, '<script onload="alert(1)"> & x', 'isolated']
    return LineageGraph([{'asset_id': str(i), 'name': n, 'kind': 'unresolved' if i == 1 else 'table',
                          'temporary': i == 0} for i, n in enumerate(names)], [
        {'edge_id': str(i), 'source_id': s, 'target_id': t, 'code': 'PRIVATE SOURCE'}
        for i, (s, t) in enumerate([('0', '1'), ('1', '0'), ('0', '0')])])


def test_standalone_svg_uses_shared_scene_and_inert_full_titles():
    g = graph()
    scene = graph_data(g)
    data, meta = images.render_graph_image(g, format='svg', scope={'warnings': ['Depth boundary reached']})
    root = ET.fromstring(data)
    assert root.tag == '{http://www.w3.org/2000/svg}svg'
    assert len(root.findall('.//s:g[@data-node]', NS)) == len(scene['nodes'])
    paths = root.findall('.//s:path[@data-edge]', NS)
    assert [p.get('d') for p in paths] == [e['path'] for e in scene['edges']]
    assert all(p.get('marker-end') == 'url(#df-arrow)' for p in paths)
    assert 'PRIVATE SOURCE' not in data.decode()
    assert '<script' not in data.decode()
    assert g.nodes['0']['name'] in ''.join(root.itertext())
    assert 'Depth boundary reached' in ''.join(root.itertext())
    assert meta['node_count'] == 3 and meta['edge_count'] == 3
    assert not any(k.startswith('on') or k.endswith('href') for e in root.iter() for k in e.attrib)


@pytest.mark.parametrize('background', ['light', 'dark', 'transparent'])
def test_real_png_dimensions_scale_and_background(background):
    import io

    from PIL import Image

    opts = images.ImageOptions(background=background, scale=2)
    svg, sm = images.render_graph_image(graph(), format='svg', options=opts)
    png, pm = images.render_graph_image(graph(), format='png', options=opts)
    assert png.startswith(b'\x89PNG\r\n\x1a\n')
    assert struct.unpack('>II', png[16:24]) == (pm['width'], pm['height']) == (sm['width'], sm['height'])
    image = Image.open(io.BytesIO(png)).convert('RGBA')
    pixel = image.getpixel((0, 0))
    assert pixel == {'light': (255, 255, 255, 255), 'dark': (23, 30, 41, 255),
                     'transparent': (0, 0, 0, 0)}[background]
    assert b'<svg' in svg


def test_empty_and_excessive_graphs_fail_actionably():
    with pytest.raises(ValueError, match='no nodes'):
        images.render_graph_image(LineageGraph([], []))
    huge = LineageGraph([{'asset_id': str(i), 'name': str(i)} for i in range(1001)], [])
    with pytest.raises(ValueError, match='1000'):
        images.render_graph_image(huge)


def test_label_modes_and_determinism():
    for mode in ['hidden', 'compact', 'full']:
        appearance = VisualizationSettings(graph_labels=mode, graph_edge_width=5, graph_palette='neutral')
        a, _ = images.render_graph_image(graph(), appearance=appearance)
        b, _ = images.render_graph_image(graph(), appearance=appearance)
        assert a == b
        root = ET.fromstring(a)
        assert all(e.get('stroke-width') == '5' for e in root.findall('.//s:path[@data-edge]', NS))
        assert bool(root.findall('.//s:g[@data-node]/s:text', NS)) == (mode != 'hidden')


def test_single_node_and_pixel_bounds():
    one = LineageGraph([{'asset_id': 'x', 'name': 'single'}], [])
    data, meta = images.render_graph_image(one)
    assert meta['node_count'] == 1 and ET.fromstring(data).get('viewBox')
    wide = LineageGraph([{'asset_id': str(i), 'name': str(i)} for i in range(100)], [
        {'edge_id': str(i), 'source_id': str(i), 'target_id': str(i+1)} for i in range(99)])
    with pytest.raises(ValueError, match='8192|pixels'):
        images.render_graph_image(wide, format='png')


def test_png_missing_capability_and_timeout(monkeypatch):
    monkeypatch.setattr(images, 'png_available', lambda: False)
    with pytest.raises(ValueError, match='SVG|resvg'):
        images.render_graph_image(graph(), format='png')
    monkeypatch.setattr(images, 'png_available', lambda: True)
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('renderer', 15)
    monkeypatch.setattr(images.subprocess, 'run', timeout)
    with pytest.raises(ValueError, match='time limit'):
        images.render_graph_image(graph(), format='png')


def test_wide_title_wraps_to_fitted_canvas():
    one = LineageGraph([{'asset_id': 'x', 'name': 'single'}], [])
    data, meta = images.render_graph_image(one, options={'title': 'W' * 90, 'legend': False})
    root = ET.fromstring(data)
    annotations = root.findall('s:text', NS)
    assert len(annotations) == 2
    assert ''.join(t.text for t in annotations) == 'W' * 90
    assert all(len(t.text) * 14 <= meta['width'] - 40 for t in annotations)


def test_png_parallel_jobs_are_bounded():
    assert images.RENDER_SLOTS.acquire(blocking=False)
    assert images.RENDER_SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match='busy'):
            images.render_graph_image(graph(), format='png')
    finally:
        images.RENDER_SLOTS.release()
        images.RENDER_SLOTS.release()
