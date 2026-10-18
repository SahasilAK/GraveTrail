import tomllib
from pathlib import Path

import pytest


def test_curated_additions_preserve_all_fourteen_existing_themes():
    import hashlib
    import json

    from ui.themes import PRESETS

    existing = [f"{name} {mode}" for mode in ("dark", "light")
                for name in ("Ocean", "Forest", "Amethyst", "Graphite")]
    assert list(PRESETS)[:8] == existing
    # Frozen definitions from 4430206; adding options must not recolor or rename these.
    digest = hashlib.sha256(json.dumps({n: PRESETS[n] for n in existing}, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    assert digest == "6e15dbd1a2fd9528b1b2353c5188ed503d36b767bf4fb8dec5b49b7f4cfae7df"
    assert set(PRESETS) - set(existing) == {
        "Claude orange light", "Claude orange dark", "Nord light", "Rose light", "Sand light", "Mint light",
        "Porcelain light", "Celadon light", "Ink dark", "Aubergine dark"}
    assert len(PRESETS) == 18
    original = dict(list(PRESETS.items())[:14])
    assert hashlib.sha256(json.dumps(original, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == (
        "6f46cc33aaaaa96b56ac89926849cd8c3e53b27f2b2af63b6da29066f730a0e5")


def test_theme_presets_apply_both_modes_and_preserve_other_configuration(tmp_path):
    from ui.themes import PRESETS, apply_preset, current_preset

    config = tmp_path / "config.toml"
    original = Path(".streamlit/config.toml").read_text(encoding="utf-8")
    config.write_text(original, encoding="utf-8")
    expected = tomllib.loads(original)
    for name in PRESETS:
        apply_preset(config, name)
        assert current_preset(config) == name
        result = tomllib.loads(config.read_text(encoding="utf-8"))
        assert result["server"] == expected["server"]
        assert result["browser"] == expected["browser"]
        assert result["theme"]["font"] == expected["theme"]["font"]
        assert "light" not in result["theme"] and "dark" not in result["theme"]
        for key, value in PRESETS[name].items():
            assert result["theme"][key] == value
    before = config.read_bytes()
    with pytest.raises(ValueError):
        apply_preset(config, "../../not-a-theme")
    assert config.read_bytes() == before


def test_theme_update_preserves_custom_sidebar_and_unrelated_keys(tmp_path):
    from ui.themes import apply_preset, current_preset

    config = tmp_path / "config.toml"
    config.write_text('[server]\nport = 9999 # user port\n[theme]\nfont = "serif"\n'
                      '[theme.light]\nprimaryColor = "#123456" # previous accent\nbuttonRadius = "small"\n'
                      '[theme.light.sidebar]\npaddingTop = "2rem"\n', encoding="utf-8")
    assert current_preset(config) is None
    apply_preset(config, "Forest light")
    text = config.read_text(encoding="utf-8")
    result = tomllib.loads(text)
    assert '# user port' in text and result["server"]["port"] == 9999
    assert result["theme"]["font"] == "serif"
    assert result["theme"]["buttonRadius"] == "small"
    assert result["theme"]["sidebar"]["paddingTop"] == "2rem"
    assert current_preset(config) == "Forest light"


def test_failed_theme_publication_preserves_previous_config(tmp_path, monkeypatch):
    from ui.themes import apply_preset

    config = tmp_path / "config.toml"
    config.write_text('[theme]\nfont = "sans-serif"\n', encoding="utf-8")
    previous = config.read_bytes()
    def fail(*args):
        raise OSError("Read-only configuration")
    monkeypatch.setattr("ui.themes.os.replace", fail)
    with pytest.raises(OSError):
        apply_preset(config, "Amethyst dark")
    assert config.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [config]


@pytest.mark.parametrize("header", ['[theme.light]', '  [theme.light]', '[theme."light"]'])
def test_theme_update_handles_valid_multiline_and_quoted_toml(tmp_path, header):
    from ui.themes import apply_preset, current_preset

    config = tmp_path / "config.toml"
    config.write_text('[server]\nport = 9999 # preserve this\n' + header + '\n'
                      'chartCategoricalColors = [\n  "#123456",\n  "#abcdef",\n]\n', encoding="utf-8")
    apply_preset(config, "Amethyst dark")
    assert current_preset(config) == "Amethyst dark"
    assert tomllib.loads(config.read_text())["server"]["port"] == 9999
    assert "# preserve this" in config.read_text()


def test_presets_keep_readable_text_links_and_primary_buttons():
    from ui.themes import PRESETS

    def luminance(color):
        channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(v * w for v, w in zip(linear, [.2126, .7152, .0722]))
    def contrast(first, second):
        high, low = sorted([luminance(first), luminance(second)], reverse=True)
        return (high + .05) / (low + .05)
    for name, colors in PRESETS.items():
        for background in ("backgroundColor", "secondaryBackgroundColor"):
            assert contrast(colors["textColor"], colors[background]) >= 4.5, name
            assert contrast(colors["linkColor"], colors[background]) >= 4.5, name
        assert contrast("#ffffff", colors["primaryColor"]) >= 4.5, name
