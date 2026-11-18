from pathlib import Path
from typing import Any

import pytest


def test_failed_theme_publication_preserves_previous_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that failed theme publication preserves previous config.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        OSError: Raised by the test helper.
    """
    from ui.themes import apply_preset

    config = tmp_path / "config.toml"
    config.write_text('[theme]\nfont = "sans-serif"\n', encoding="utf-8")
    previous = config.read_bytes()
    def fail(*args: Any) -> None:
        """Raise the injected failure used by the test.

        Args:
            args: Positional arguments forwarded to the operation.

        Raises:
            OSError: Raised by the test helper.
        """
        raise OSError("Read-only configuration")
    monkeypatch.setattr("ui.themes.os.replace", fail)
    with pytest.raises(OSError):
        apply_preset(config, "Amethyst Terminal")
    assert config.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [config]
