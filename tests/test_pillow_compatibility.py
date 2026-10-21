"""Temporary, exact Streamlit/Pillow compatibility exception and real image paths."""
import io
import tomllib
from importlib.metadata import distributions, version
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from PIL import Image
from streamlit.elements.lib.image_utils import _ensure_image_size_and_format
from streamlit.elements.lib.layout_utils import LayoutConfig


def test_security_pins_apply_to_project_override_and_package_installers():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    pin = 'pillow==13.0.0'
    assert pin in project['project']['dependencies']  # Plain resolvers must not install vulnerable Pillow.
    assert 'streamlit==1.66.0' in project['project']['dependencies']
    assert project['tool']['uv']['override-dependencies'] == [pin]
    assert [line for line in (root / 'dependency-overrides.txt').read_text(encoding='utf-8').splitlines()
            if line and not line.startswith('#')] == [pin]
    assert version('pillow') == '13.0.0' and version('streamlit') == '1.66.0'


def test_only_the_documented_streamlit_pillow_metadata_bound_is_overridden():
    exceptions = []
    for installed in distributions():
        for text in installed.requires or []:
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
                continue
            actual = version(requirement.name)
            if requirement.specifier and actual not in requirement.specifier:
                exceptions.append((installed.metadata['Name'].lower(), requirement.name.lower(), actual))
    assert exceptions == [('streamlit', 'pillow', '13.0.0')]


@pytest.mark.parametrize('mode,output', [('RGB', 'JPEG'), ('RGBA', 'PNG'), ('L', 'PNG'), ('P', 'PNG')])
def test_streamlit_resizes_and_reencodes_images_with_patched_pillow(mode, output):
    image = Image.new(mode, (64, 32))
    source = io.BytesIO()
    image.save(source, format='PNG')
    result = _ensure_image_size_and_format(source.getvalue(), LayoutConfig(width=16), output)
    with Image.open(io.BytesIO(result)) as decoded:
        decoded.load()
        assert decoded.size == (16, 8) and decoded.format == output


def test_streamlit_renders_bundled_icon_and_array_through_public_api():
    from streamlit.testing.v1 import AppTest
    root = Path(__file__).resolve().parents[1]
    def render(icon):
        import numpy as np
        import streamlit as st
        st.image(icon, width=32, alt='GraveTrail icon')
        st.image(np.zeros((8, 16, 3), dtype=np.uint8), width=8, alt='Array image')
    view = AppTest.from_function(render, args=(str(root / 'ui/icon.png'),)).run()
    assert not view.exception and len(view.get('image')) == 2
