"""Native app-wide palette presets; preserve server options and custom layout configuration."""
import os
import tempfile
import threading
import tomllib
from collections.abc import MutableMapping
from pathlib import Path

import tomlkit

CONFIG_PATH = Path(os.environ.get('DATAFORGE_THEME_CONFIG', str(Path(__file__).resolve().parents[2] / '.streamlit' / 'config.toml')))
_LOCK = threading.Lock()


def _colors(primary, background, secondary, text, border, link, chart):
    return dict(primaryColor=primary, backgroundColor=background, secondaryBackgroundColor=secondary,
                textColor=text, borderColor=border, linkColor=link, chartCategoricalColors=chart)


PALETTES = {
    "Ocean": {
        "light": _colors("#2869c7", "#ffffff", "#f1f5fa", "#17324d", "#d7e0ea", "#2869c7",
                         ["#2869c7", "#177e89", "#9465bb", "#b66a16"]),
        "dark": _colors("#2869c7", "#15202e", "#1f2e40", "#e7eef7", "#3b4f65", "#9abcf0",
                        ["#71a7ee", "#52c5c5", "#bb9cde", "#e1ad66"]),
    },
    "Forest": {
        "light": _colors("#16765b", "#fcfefc", "#edf4ef", "#20392e", "#c6d8cc", "#15694f",
                         ["#16765b", "#4e708f", "#947040", "#786393"]),
        "dark": _colors("#16765b", "#14251f", "#20382d", "#e3f2eb", "#4b6658", "#8bd3b1",
                        ["#80c8a1", "#8eb8df", "#d9b77d", "#bea1d7"]),
    },
    "Amethyst": {
        "light": _colors("#76509e", "#fdfcfe", "#f2edf7", "#362743", "#d8cce3", "#704897",
                         ["#76509e", "#347d83", "#a26743", "#526ca3"]),
        "dark": _colors("#76509e", "#221b30", "#322840", "#f0e9fa", "#645476", "#c7a9ed",
                        ["#c1a0e5", "#82c5cb", "#dfae88", "#99b2e9"]),
    },
    "Graphite": {
        "light": _colors("#526171", "#fdfdfd", "#edf0f3", "#26303a", "#c4cbd3", "#43566a",
                         ["#526171", "#397e88", "#8c7055", "#806d92"]),
        "dark": _colors("#526171", "#1e2227", "#2b3139", "#edf0f4", "#5b6570", "#b6c5d6",
                        ["#b6c5d6", "#85bdc5", "#ccb08c", "#b7a4cb"]),
    },
}

PRESETS = {f"{name} {mode}": {"base": mode, **modes[mode]}
           for mode in ("dark", "light") for name, modes in PALETTES.items()}

# Additional choices leave the original eight definitions and their order intact.
PRESETS.update({
    "Claude orange light": {"base": "light", **_colors(
        "#a84b2f", "#faf7f2", "#eee7dc", "#3d332c", "#d6cabb", "#a0482e",
        ["#a84b2f", "#607568", "#8c7197", "#92733f"])},
    "Claude orange dark": {"base": "dark", **_colors(
        "#a84b2f", "#26231f", "#342e28", "#f0e7dd", "#746354", "#edaa85",
        ["#e6a180", "#a0baa2", "#c6a8d3", "#d6bd87"])},
    "Nord light": {"base": "light", **_colors(
        "#466384", "#f4f7fb", "#e6edf5", "#2e3440", "#c5d0df", "#3e5d7e",
        ["#466384", "#4b7a81", "#8b6799", "#9b7046"])},
    "Rose light": {"base": "light", **_colors(
        "#9d4162", "#fffafb", "#f8eaf0", "#4a2938", "#dfc3cf", "#963857",
        ["#9d4162", "#527e78", "#7d6ba8", "#9a7138"])},
    "Sand light": {"base": "light", **_colors(
        "#886315", "#fcfaf4", "#eee9dc", "#403b2e", "#d4c9af", "#76540f",
        ["#886315", "#4e7772", "#8d6689", "#586d9a"])},
    "Mint light": {"base": "light", **_colors(
        "#226d5a", "#f7fcfa", "#e6f2ee", "#253d36", "#bed8cf", "#1c6654",
        ["#226d5a", "#5679a1", "#937042", "#8b679c"])},
})


def current_preset(path):
    theme = tomllib.loads(Path(path).read_text(encoding="utf-8")).get("theme", {})
    return next((name for name, values in PRESETS.items() if all(
        theme.get(key) == value for key, value in values.items())
        and not theme.get("light") and not theme.get("dark")), None)


def apply_preset(path, name):
    if name not in PRESETS:
        raise ValueError("Choose a supported theme preset")
    path = Path(path)
    with _LOCK:
        if path.is_symlink():
            raise ValueError("Theme configuration cannot be a symlink")
        text = path.read_text(encoding="utf-8")
        tomllib.loads(text)  # Refuse to rewrite malformed configuration.
        document = tomlkit.parse(text)
        theme = document.setdefault("theme", tomlkit.table())
        if not isinstance(theme, MutableMapping):
            raise ValueError("Theme configuration must be a table")
        mode = PRESETS[name]["base"]
        # A single native theme makes dark selection explicit, even if the browser used Light.
        # Keep layout/sidebar overrides from the selected appearance while replacing colors.
        selected = theme.pop(mode, {})
        other = theme.pop("light" if mode == "dark" else "dark", {})
        if not isinstance(selected, MutableMapping) or not isinstance(other, MutableMapping):
            raise ValueError("Theme appearance must be a table")
        for section in (other, selected):
            for key, value in section.items():
                if key == "sidebar":
                    sidebar = theme.setdefault("sidebar", tomlkit.table())
                    if not isinstance(sidebar, MutableMapping) or not isinstance(value, MutableMapping):
                        raise ValueError("Theme sidebar must be a table")
                    sidebar.update(value)
                elif key not in PRESETS[name]:
                    theme[key] = value
        theme.update(PRESETS[name])
        text = tomlkit.dumps(document)
        tomllib.loads(text)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".theme-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)


