"""Static exports retain the UI scene while excluding source and active content."""
import struct
from typing import Any
from xml.etree import ElementTree as ET

import pytest

from dataforge import graph_images as images
from dataforge.exports import graph_data
from dataforge.graph import LineageGraph

NS = {'s': 'http://www.w3.org/2000/svg'}


def graph() -> Any:
    """Provide the graph fixture used by the tests.

    Returns:
        Value produced for the test scenario.
    """
    names = ['日本語_' + 'long_' * 60, '<script onload="alert(1)"> & x', 'isolated']
    return LineageGraph([{'asset_id': str(i), 'name': n, 'kind': 'unresolved' if i == 1 else 'table',
                          'temporary': i == 0} for i, n in enumerate(names)], [
        {'edge_id': str(i), 'source_id': s, 'target_id': t, 'code': 'PRIVATE SOURCE'}
        for i, (s, t) in enumerate([('0', '1'), ('1', '0'), ('0', '0')])])


def test_standalone_svg_uses_shared_scene_and_inert_full_titles() -> None:
    """Verify that standalone svg uses shared scene and inert full titles."""
    g = graph()
    scene = graph_data(g)
    data, meta = images.render_graph_image(g, format='svg', scope={'warnings': ['Depth boundary reached']})
    root = ET.fromstring(data)
    assert root.tag == '{http://www.w3.org/2000/svg}svg'
    assert len(root.findall('.//s:g[@data-node]', NS)) == len(scene['nodes'])
    paths = root.findall('.//s:path[@data-edge]', NS)
    assert [p.get('d') for p in paths] == [e['path'] for e in scene['edges']]
    assert all(p.get('marker-end') == 'url(#df-arrow)' for p in paths)
    marker = root.find('.//s:marker', NS)
    assert marker.get('markerUnits') == 'userSpaceOnUse'
    assert marker.find('s:path', NS).get('fill') == 'none'
    assert 'PRIVATE SOURCE' not in data.decode()
    assert '<script' not in data.decode()
    assert g.nodes['0']['name'] in ''.join(root.itertext())
    assert 'Depth boundary reached' in ''.join(root.itertext())
    assert meta['node_count'] == 3 and meta['edge_count'] == 3
    assert not any(k.startswith('on') or k.endswith('href') for e in root.iter() for k in e.attrib)


def test_real_png_dimensions_scale_and_background() -> None:
    """Verify real PNG output dimensions and transparent alpha."""
    import io

    from PIL import Image

    opts = images.ImageOptions(background='transparent', scale=2)
    svg, sm = images.render_graph_image(graph(), format='svg', options=opts)
    png, pm = images.render_graph_image(graph(), format='png', options=opts)
    assert png.startswith(b'\x89PNG\r\n\x1a\n')
    assert struct.unpack('>II', png[16:24]) == (pm['width'], pm['height']) == (sm['width'], sm['height'])
    image = Image.open(io.BytesIO(png)).convert('RGBA')
    pixel = image.getpixel((0, 0))
    assert pixel == (0, 0, 0, 0)
    assert b'<svg' in svg


def test_png_missing_capability_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that png missing capability and timeout.

    Args:
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        subprocess.TimeoutExpired: Raised by the test helper.
    """
    monkeypatch.setattr(images, 'png_available', lambda: False)
    with pytest.raises(ValueError, match='SVG|resvg'):
        images.render_graph_image(graph(), format='png')
    monkeypatch.setattr(images, 'png_available', lambda: True)
    import subprocess
    def timeout(*args: Any, **kwargs: Any) -> None:
        """Handle timeout for the test scenario.

        Args:
            args: Positional arguments forwarded to the operation.
            kwargs: Keyword arguments forwarded to the operation.

        Raises:
            subprocess.TimeoutExpired: Raised by the test helper.
        """
        raise subprocess.TimeoutExpired('renderer', 15)
    monkeypatch.setattr(images.subprocess, 'run', timeout)
    with pytest.raises(ValueError, match='time limit'):
        images.render_graph_image(graph(), format='png')
