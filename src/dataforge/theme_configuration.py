"""Native app-wide palette presets; preserve server options and custom layout configuration."""
import os
import tempfile
import threading
import tomllib
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(os.environ.get('DATAFORGE_THEME_CONFIG', str(Path(__file__).resolve().parents[2] / '.streamlit' / 'config.toml')))
_LOCK = threading.Lock()


def _colors(
    primary: str,
    background: str,
    secondary: str,
    text: str,
    border: str,
    link: str,
    chart: list[str],
) -> dict[str, Any]:
    """Build the native Streamlit color settings for a palette."""
    return dict(primaryColor=primary, backgroundColor=background, secondaryBackgroundColor=secondary,
                textColor=text, borderColor=border, linkColor=link, chartCategoricalColors=chart)


def _palette(mode: str, ui: str, graph: str, description: str) -> dict[str, str]:
    """Map UI and graph color rows to the named palette roles."""
    # Roles stay fixed; future palettes only supply another row of values.
    roles = "bg sidebar surface accent text muted border source intermediate target path edge graph selected".split()
    return dict(zip(roles, (ui + " " + graph).lower().split(), strict=True), mode=mode, description=description)


PALETTES = {
    "Obsidian & Ember": _palette("dark",
        "#0A0B0D #11161C #1A2230 #F97316 #F8FAFC #9CA3AF #2A3240",
        "#F97316 #F59E0B #FDBA74 #FF8A3D #475569 #0D1117 #FDE68A", "Dark · Premium · Industrial"),
    "Arctic Mint": _palette("light",
        "#F8FFFD #E6F7F4 #FFFFFF #14B8A6 #0F172A #64748B #D6EDE9",
        "#10B981 #34D399 #60A5FA #2DD4BF #94D2BD #F1FDFA #A7F3D0", "Light · Clean · Modern"),
    "Amethyst Terminal": _palette("dark",
        "#0A0614 #150B28 #1E1340 #8B5CF6 #F8F6FF #A78BFA #2D1B53",
        "#A855F7 #C084FC #818CF8 #D946EF #6B46C1 #0F0820 #E9D5FF", "Dark · Futuristic · Developer-focused"),
    "Fossil & Copper": _palette("light",
        "#FFFAF5 #F2E6D9 #FFFFFF #C9693C #2D1F14 #7A6A58 #E6D8C7",
        "#C9693C #D7875A #E8B895 #FF9E73 #B09A8A #FCF6F1 #FCD34D", "Light · Editorial · Distinctive"),
    "Carbon & Volt": _palette("dark",
        "#050A08 #0B1F14 #10281D #84CC16 #ECFDF5 #86A792 #1F3A2B",
        "#22C55E #10B981 #14F195 #A3E635 #2F6B52 #06140E #D9F99D", "Dark · Bold · High-tech"),
    "Crimson Forge": _palette("dark",
        "#0A0D12 #141821 #1E242E #DC2626 #F1F5F9 #94A3B8 #2E3642",
        "#22C55E #3B82F6 #EF4444 #F97316 #64748B #0F1117 #FDE047", "Dark · Bold · Industrial"),
    "Cobalt Atlas": _palette("dark",
        "#0A1320 #0F2138 #152B46 #0EA5E9 #E2E8F0 #94A3B8 #2A3F5F",
        "#22C55E #3B82F6 #A855F7 #38BDF8 #64748B #0B1524 #FDE68A", "Dark · Technical · Trustworthy"),
    "Rose Circuit": _palette("dark",
        "#150B18 #24142A #2D1B34 #EC4899 #F8FAFC #A78BFA #3B2A45",
        "#22C55E #8B5CF6 #EC4899 #F472B6 #6B7280 #150B18 #F9A8D4", "Dark · Elegant · Modern"),
    "Steel Glacier": _palette("dark",
        "#0E1A26 #1F2F3F #263B4D #22D3EE #E2E8F0 #94A3B8 #334155",
        "#22C55E #38BDF8 #60A5FA #67E8F9 #64748B #0E1A26 #A7F3D0", "Cool · Minimal · Analytical"),
}


def contrast(first: str, second: str) -> float:
    """Calculate the WCAG contrast ratio between two hexadecimal colors."""

    def luminance(color: str) -> float:
        """Convert an sRGB hex color to relative luminance."""
        rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        return sum((v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4) * w
                   for v, w in zip(rgb, (.2126, .7152, .0722)))
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + .05) / (low + .05)


def on_accent(color: str) -> str:
    """Choose whichever of black and white contrasts better with the accent."""
    return max(("#ffffff", "#000000"), key=lambda text: contrast(text, color))


def hover_accent(color: str) -> str:
    """Blend an accent toward its higher-contrast foreground for hover states."""
    tint = 255 if on_accent(color) == "#000000" else 0
    return "#" + "".join(f"{round(int(color[i:i + 2], 16) * .9 + tint * .1):02x}" for i in (1, 3, 5))


def readable_accent(palette: dict[str, str]) -> str:
    """Adjust a palette accent toward its text color until it meets contrast targets."""
    accent, text = ([int(palette[key][i:i + 2], 16) for i in (1, 3, 5)] for key in ("accent", "text"))
    for weight in range(11):
        color = "#" + "".join(f"{round((a * (10 - weight) + t * weight) / 10):02x}" for a, t in zip(accent, text))
        if all(contrast(color, palette[bg]) >= 4.5 for bg in ("bg", "surface", "sidebar")):
            return color
    return palette["text"]


# These native definitions are intentionally unchanged, including inherited sidebar colors.
PRESETS = {
    "Ocean dark": {"base": "dark", **_colors(
        "#2869c7", "#15202e", "#1f2e40", "#e7eef7", "#3b4f65", "#9abcf0",
        ["#71a7ee", "#52c5c5", "#bb9cde", "#e1ad66"])},
    "Ink dark": {"base": "dark", **_colors(
        "#4169ad", "#17191e", "#22252c", "#eceef2", "#404650", "#a9bfe7",
        ["#a9bfe7", "#8abaaa", "#d4b482", "#bea4ca"])},
}
for name, p in PALETTES.items():
    link = readable_accent(p)
    PRESETS[name] = {"base": p["mode"], **_colors(p["accent"], p["bg"], p["surface"], p["text"], p["border"],
        link, [p["source"], p["intermediate"], p["target"], p["path"]]),
        "sidebar": {"backgroundColor": p["sidebar"], "secondaryBackgroundColor": p["surface"]}}

PRESET_DESCRIPTIONS = {name: p["description"] for name, p in PALETTES.items()}
PRESET_DESCRIPTIONS.update({"Ocean dark": "Original ocean-blue appearance.",
                           "Ink dark": "Original graphite and cobalt appearance."})

# Pages keeps its original Ink/Celadon schemes and uses the same nine new definitions.
SITE_THEMES = {"celadon": "Celadon light", "slate": "Ink dark",
               **{name.lower().replace(" & ", "-").replace(" ", "-"): name for name in PALETTES}}


def site_theme_css() -> str:
    """Generate CSS variables for palettes published by the documentation site."""
    blocks = []
    roles = {"paper": "bg", "surface": "surface", "sidebar": "sidebar", "ink": "text",
             "muted": "muted", "line": "border", "accent": "accent", "string": "source"}
    for scheme, name in SITE_THEMES.items():
        if name not in PALETTES:
            continue
        p = PALETTES[name]
        tokens = {key: p[role] for key, role in roles.items()}
        tokens.update(link=PRESETS[name]["linkColor"], **{"on-accent": on_accent(p["accent"]),
                      "accent-hover": hover_accent(p["accent"]),
                      "shadow": "0 1rem 3rem #0003" if p["mode"] == "dark" else "0 1rem 3rem #242a3010"})
        blocks.append(f'[data-md-color-scheme="{scheme}"]' + "{color-scheme:" + p["mode"] + ";" +
                      ";".join(f"--gt-{key}:{value}" for key, value in tokens.items()) + "}")
    return "\n".join(blocks)


def matches_preset(theme: object, values: dict[str, Any]) -> bool:
    """Check whether a parsed theme mapping contains all requested preset values."""
    if not isinstance(theme, MutableMapping):
        return False
    return all(matches_preset(theme.get(key, {}), value) if isinstance(value, dict)
               else theme.get(key) == value for key, value in values.items())


def current_preset(path: str | Path) -> str | None:
    """Return the matching native preset name, or ``None`` for a customized theme."""
    theme = tomllib.loads(Path(path).read_text(encoding="utf-8")).get("theme", {})
    return next((name for name, values in PRESETS.items() if matches_preset(theme, values)
        and not theme.get("light") and not theme.get("dark")), None)


def apply_preset(path: str | Path, name: str) -> None:
    """Apply a native palette while preserving unrelated layout and server settings.

    Args:
        path: Streamlit TOML configuration file to update.
        name: Name of a supported theme preset.

    Raises:
        ValueError: If the preset or existing configuration structure is invalid.
    """
    import tomlkit

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
        # Replace owned colors while retaining sidebar padding, fonts and other layout overrides.
        sidebar = theme.get("sidebar", {})
        if not isinstance(sidebar, MutableMapping):
            raise ValueError("Theme sidebar must be a table")
        for key in ("backgroundColor", "secondaryBackgroundColor"):
            sidebar.pop(key, None)
        sidebar.update(PRESETS[name].get("sidebar", {}))
        if sidebar:
            theme["sidebar"] = sidebar
        else:
            theme.pop("sidebar", None)
        theme.update({key: value for key, value in PRESETS[name].items() if key != "sidebar"})
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


