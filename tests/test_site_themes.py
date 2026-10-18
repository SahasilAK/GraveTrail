"""The four published appearances stay coordinated with native app palettes."""
import re
from pathlib import Path

import pytest

from dataforge.theme_configuration import PRESETS


def test_site_has_four_palettes_and_publishes_the_native_theme_selector():
    config = pytest.importorskip('mkdocs.config').load_config('mkdocs.yml')
    schemes = [palette['scheme'] for palette in config.theme['palette']]
    assert schemes == ['default', 'slate', 'celadon', 'aubergine']
    assert 'assets/javascripts/themes.js' in config.extra_javascript
    assert 'assets/javascripts/themes.js' in config.extra['public_assets']


def test_site_palettes_match_app_surfaces_and_actions():
    css = Path('docs/assets/stylesheets/extra.css').read_text(encoding='utf-8')
    for scheme, name in [('default', 'Porcelain light'), ('celadon', 'Celadon light'),
                         ('slate', 'Ink dark'), ('aubergine', 'Aubergine dark')]:
        block = re.search(r'\[data-md-color-scheme="' + scheme + r'"\]\s*\{([^}]+)', css)[1]
        tokens = dict(re.findall(r'--gt-([\w-]+):\s*(#[\da-f]{6})\s*;', block))
        for token, native in {'paper': 'backgroundColor', 'surface': 'secondaryBackgroundColor',
                              'ink': 'textColor', 'line': 'borderColor', 'link': 'linkColor',
                              'accent': 'primaryColor'}.items():
            assert tokens[token] == PRESETS[name][native], (scheme, token)
