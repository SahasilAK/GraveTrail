"""Published appearances share the app registry and retain Ink/Celadon."""
import re
from pathlib import Path

import pytest

from dataforge.theme_configuration import PALETTES, PRESETS
from scripts.docs.hooks import on_config


def test_site_publishes_eleven_palettes_with_native_persistence():
    config = on_config(pytest.importorskip('mkdocs.config').load_config('mkdocs.yml'))
    schemes = [palette['scheme'] for palette in config.theme['palette']]
    assert schemes == ['obsidian-ember', 'celadon', 'slate', 'arctic-mint', 'amethyst-terminal',
        'fossil-copper', 'carbon-volt', 'crimson-forge', 'cobalt-atlas', 'rose-circuit', 'steel-glacier']
    assert all('media' not in palette for palette in config.theme['palette'])
    assert 'assets/javascripts/themes.js' in config.extra_javascript
    assert 'assets/javascripts/themes.js' in config.extra['public_assets']


def test_published_new_theme_tokens_match_app_and_sidebar_roles():
    config = on_config(pytest.importorskip('mkdocs.config').load_config('mkdocs.yml'))
    css = config.extra['palette_css']
    for entry in config.theme['palette']:
        name = entry['toggle']['name']
        if name not in PALETTES:
            continue
        block = re.search(r'\[data-md-color-scheme="' + entry['scheme'] + r'"\]\{([^}]+)', css)[1]
        tokens = dict(re.findall(r'--gt-([\w-]+):\s*(#[\da-f]{6})\s*[;}]?', block))
        for token, native in {'paper': 'backgroundColor', 'surface': 'secondaryBackgroundColor',
                              'ink': 'textColor', 'line': 'borderColor', 'link': 'linkColor',
                              'accent': 'primaryColor'}.items():
            assert tokens[token] == PRESETS[name][native], (name, token)
        assert tokens['sidebar'] == PALETTES[name]['sidebar']
    legacy = Path('docs/assets/stylesheets/extra.css').read_text(encoding='utf-8')
    assert '--gt-paper: #f4f7f2' in legacy and '--gt-paper: #17191e' in legacy
    assert 'data-md-color-scheme="default"' not in legacy
    assert 'data-md-color-scheme="aubergine"' not in legacy
