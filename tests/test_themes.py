import tomllib
from pathlib import Path

import pytest


def test_palette_choices_preserve_ocean_and_ink_and_default_to_ocean():
    from ui.themes import PRESETS

    assert list(PRESETS)[:2] == ["Ocean dark", "Ink dark"]
    assert set(PRESETS) == {"Ocean dark", "Ink dark", "Obsidian & Ember", "Arctic Mint",
        "Amethyst Terminal", "Fossil & Copper", "Carbon & Volt", "Crimson Forge",
        "Cobalt Atlas", "Rose Circuit", "Steel Glacier"}
    assert PRESETS["Ocean dark"] == dict(base="dark", primaryColor="#2869c7", backgroundColor="#15202e",
        secondaryBackgroundColor="#1f2e40", textColor="#e7eef7", borderColor="#3b4f65", linkColor="#9abcf0",
        chartCategoricalColors=["#71a7ee", "#52c5c5", "#bb9cde", "#e1ad66"])
    assert PRESETS["Ink dark"] == dict(base="dark", primaryColor="#4169ad", backgroundColor="#17191e",
        secondaryBackgroundColor="#22252c", textColor="#eceef2", borderColor="#404650", linkColor="#a9bfe7",
        chartCategoricalColors=["#a9bfe7", "#8abaaa", "#d4b482", "#bea4ca"])
    from ui.themes import current_preset
    assert current_preset(".streamlit/config.toml") == "Ocean dark"


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
    apply_preset(config, "Arctic Mint")
    text = config.read_text(encoding="utf-8")
    result = tomllib.loads(text)
    assert '# user port' in text and result["server"]["port"] == 9999
    assert result["theme"]["font"] == "serif"
    assert result["theme"]["buttonRadius"] == "small"
    assert result["theme"]["sidebar"]["paddingTop"] == "2rem"
    assert current_preset(config) == "Arctic Mint"


def test_failed_theme_publication_preserves_previous_config(tmp_path, monkeypatch):
    from ui.themes import apply_preset

    config = tmp_path / "config.toml"
    config.write_text('[theme]\nfont = "sans-serif"\n', encoding="utf-8")
    previous = config.read_bytes()
    def fail(*args):
        raise OSError("Read-only configuration")
    monkeypatch.setattr("ui.themes.os.replace", fail)
    with pytest.raises(OSError):
        apply_preset(config, "Amethyst Terminal")
    assert config.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [config]


@pytest.mark.parametrize("header", ['[theme.light]', '  [theme.light]', '[theme."light"]'])
def test_theme_update_handles_valid_multiline_and_quoted_toml(tmp_path, header):
    from ui.themes import apply_preset, current_preset

    config = tmp_path / "config.toml"
    config.write_text('[server]\nport = 9999 # preserve this\n' + header + '\n'
                      'chartCategoricalColors = [\n  "#123456",\n  "#abcdef",\n]\n', encoding="utf-8")
    apply_preset(config, "Amethyst Terminal")
    assert current_preset(config) == "Amethyst Terminal"
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
        from dataforge.theme_configuration import hover_accent, on_accent
        assert contrast(on_accent(colors["primaryColor"]), colors["primaryColor"]) >= 4.5, name
        assert contrast(on_accent(colors["primaryColor"]), hover_accent(colors["primaryColor"])) >= 4.5, name


def test_switching_back_to_legacy_removes_palette_sidebar_colors_only(tmp_path):
    from ui.themes import apply_preset, current_preset

    config = tmp_path / "config.toml"
    config.write_text('[theme]\nfont="serif"\n[theme.sidebar]\npaddingTop="2rem"\n', encoding="utf-8")
    apply_preset(config, "Fossil & Copper")
    assert tomllib.loads(config.read_text())["theme"]["sidebar"]["backgroundColor"] == "#f2e6d9"
    assert current_preset(config) == "Fossil & Copper"
    apply_preset(config, "Ink dark")
    assert tomllib.loads(config.read_text())["theme"]["sidebar"] == {"paddingTop": "2rem"}
    assert current_preset(config) == "Ink dark"


def test_graph_roles_follow_selected_palette_without_recoloring_legacy_graphs():
    from dataforge.exports import graph_data
    from dataforge.graph import LineageGraph

    graph = LineageGraph([dict(asset_id=n, name=n) for n in ("source", "stage", "target")],
        [dict(source_id=s, target_id=t) for s, t in (("source", "stage"), ("stage", "target"))])
    scene = graph_data(graph, theme="Cobalt Atlas")
    assert scene["theme"]["source"] == "#22c55e"
    assert scene["theme"]["intermediate"] == "#3b82f6"
    assert scene["theme"]["target"] == "#a855f7"
    assert scene["theme"]["path"] == "#38bdf8"
    assert {n["asset_id"] for n in scene["nodes"] if n["target"]} == {"target"}
    for name in (None, "Ocean dark", "Ink dark"):
        assert "theme" not in graph_data(graph, theme=name)


def test_invalid_sidebar_does_not_crash_detection_or_overwrite_configuration(tmp_path):
    import tomlkit

    from ui.themes import apply_preset, current_preset

    config = tmp_path / "config.toml"
    config.write_text('[theme]\nfont="serif"\n', encoding="utf-8")
    apply_preset(config, "Arctic Mint")
    document = tomlkit.parse(config.read_text(encoding="utf-8"))
    document["theme"]["sidebar"] = "invalid"
    config.write_text(tomlkit.dumps(document), encoding="utf-8")
    previous = config.read_bytes()
    assert current_preset(config) is None
    with pytest.raises(ValueError, match="sidebar"):
        apply_preset(config, "Ink dark")
    assert config.read_bytes() == previous


@pytest.mark.parametrize("accent", [None, "rgb(0,128,255)", "#09f"])
def test_custom_native_colors_keep_app_chrome_renderable(monkeypatch, accent):
    from ui.presentation import apply_style, brand_title

    rendered = []
    monkeypatch.setattr("ui.presentation.st.get_option", lambda key: accent if key == "theme.primaryColor" else None)
    monkeypatch.setattr("ui.presentation.st.html", rendered.append)
    apply_style()
    assert len(rendered) == 1
    if accent:
        assert f"--gt-accent:{accent}" in rendered[0]
    assert "Grave:color[Trail]" in brand_title()
