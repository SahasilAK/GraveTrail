"""Launch the same Streamlit app from a checkout, wheel or frozen bundle."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def application_root() -> Path:
    packaged = Path(__file__).resolve().parent / "_app"
    return packaged if (packaged / "app.py").is_file() else Path(__file__).resolve().parents[2]


def default_home(*, source: bool, platform: str | None = None, environ=None) -> Path:
    env = os.environ if environ is None else environ
    if env.get("DATAFORGE_HOME"):
        return Path(env["DATAFORGE_HOME"]).expanduser().resolve()
    if source:
        return Path.cwd() / ".dataforge"
    platform = platform or sys.platform
    user = Path(env.get("HOME") or env.get("USERPROFILE") or str(Path.home()))
    if platform == "win32":
        return Path(env.get("LOCALAPPDATA", str(user / "AppData/Local"))) / "DataForge"
    if platform == "darwin":
        return user / "Library/Application Support/DataForge"
    return Path(env.get("XDG_DATA_HOME", str(user / ".local/share"))) / "dataforge"


def prepare_runtime(home: Path, assets: Path) -> Path:
    target = home / ".streamlit/config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        # Exclusive creation preserves settings when two launchers race.
        try:
            with target.open("xb") as stream, (assets / ".streamlit/config.toml").open("rb") as source:
                shutil.copyfileobj(source, stream)
        except FileExistsError:
            pass
    return target


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Launch the GraveTrail engineering workspace")
    parser.add_argument("--home", type=Path, help="Persistent runtime data directory")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--address", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    args, streamlit_args = parser.parse_known_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    assets = application_root()
    source = not getattr(sys, "frozen", False) and assets.name != "_app"
    home = (args.home or default_home(source=source)).expanduser().resolve()
    os.environ["DATAFORGE_HOME"] = str(home)
    if not source:
        os.environ.setdefault("DATAFORGE_THEME_CONFIG", str(prepare_runtime(home, assets)))
        os.chdir(home)
    sys.path.insert(0, str(assets))
    from dataforge.store import Store

    store = Store(home)
    store.close()
    from streamlit.web import cli

    sys.argv = ["streamlit", "run", str(assets / "app.py"), "--server.address", args.address,
                "--server.port", str(args.port), "--server.headless", str(args.no_browser).lower(),
                "--browser.gatherUsageStats", "false", "--global.developmentMode", "false", *streamlit_args]
    raise SystemExit(cli.main())


if __name__ == "__main__":
    main()
