"""Distribution boundaries: writable homes, immutable assets and artifact integrity."""
import json
import runpy
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest


def test_gravetrail_distribution_keeps_legacy_entry_points() -> None:
    """Verify that gravetrail distribution keeps legacy entry points."""
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "gravetrail"
    for suffix in ("", "-ui", "-build"):
        assert project["scripts"]["gravetrail" + suffix] == project["scripts"]["dataforge" + suffix]


def test_frozen_cli_uses_gravetrail_program_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that frozen cli uses gravetrail program name.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes."""
    calls = []
    monkeypatch.setenv("DATAFORGE_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["gravetrail.exe", "--cli", "--help"])
    monkeypatch.setattr(sys, "path", sys.path[:])
    monkeypatch.setattr("dataforge.cli.app", lambda: calls.append(sys.argv[:]))
    root = Path(__file__).resolve().parents[1]
    runpy.run_path(str(root / "scripts/build/frozen_entry.py"), run_name="__main__")
    assert calls == [["gravetrail", "--help"]]


def test_python_build_ignores_unrelated_brand_and_previous_version_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that python build ignores unrelated brand and previous version artifacts.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        monkeypatch: Pytest fixture for isolating environment and attribute changes."""
    from dataforge.build import build_python

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    (tmp_path / 'dependency-overrides.txt').write_text('pillow==13.0.0\n', encoding='utf-8')
    output = tmp_path / "dist"
    folder = output / "python"
    folder.mkdir(parents=True)
    for name in ("unrelated_brand-1.2.3-py3-none-any.whl", "gravetrail-1.2.2-py3-none-any.whl",
                 "gravetrail-1.2.2.tar.gz", "gravetrail-1.2.3-py3-none-any.whl", "gravetrail-1.2.3.tar.gz"):
        (folder / name).write_bytes(b"artifact")
    monkeypatch.setattr("dataforge.build._run", lambda *args, **kwargs: None)
    assert {p.name for p in build_python(tmp_path, output)} == {
        "gravetrail-1.2.3-py3-none-any.whl", "gravetrail-1.2.3.tar.gz", "dependency-overrides.txt"}
    assert (folder / 'dependency-overrides.txt').read_text(encoding='utf-8') == 'pillow==13.0.0\n'
    (folder / "gravetrail-1.2.3-py3-none-any.whl").unlink()
    with pytest.raises(ValueError, match="current GraveTrail"):
        build_python(tmp_path, output)


def test_installed_home_is_outside_package_and_honors_os_conventions(tmp_path: Path) -> None:
    """Verify that installed home is outside package and honors os conventions.

    Args:
        tmp_path: Temporary directory supplied by pytest."""
    from dataforge.launcher import default_home

    assert default_home(source=False, platform="win32", environ={"LOCALAPPDATA": str(tmp_path)}) == tmp_path / "DataForge"
    assert default_home(source=False, platform="linux", environ={"XDG_DATA_HOME": str(tmp_path)}) == tmp_path / "dataforge"
    assert default_home(source=False, platform="darwin", environ={"HOME": str(tmp_path)}) == tmp_path / "Library/Application Support/DataForge"
    assert default_home(source=True, environ={}) == Path.cwd() / ".dataforge"


def test_docker_build_receives_the_required_installer_policy_file() -> None:
    """Verify Docker receives the installer policy used by packaged builds."""
    root = Path(__file__).resolve().parents[1]
    assert '!dependency-overrides.txt' in (root / '.dockerignore').read_text(encoding='utf-8').splitlines()
    copies = [line.split()[1:-1] for line in (root / 'Dockerfile').read_text(encoding='utf-8').splitlines()
              if line.startswith('COPY ') and '--from=' not in line]
    assert any('dependency-overrides.txt' in paths for paths in copies)


def test_runtime_theme_is_copied_once_and_package_is_unchanged(tmp_path: Path) -> None:
    """Verify that runtime theme is copied once and package is unchanged.

    Args:
        tmp_path: Temporary directory supplied by pytest."""
    from dataforge.launcher import prepare_runtime

    assets = tmp_path / "assets"
    (assets / ".streamlit").mkdir(parents=True)
    original = "[theme]\nbase = 'dark'\n"
    (assets / ".streamlit/config.toml").write_text(original)
    home = tmp_path / "runtime"
    target = prepare_runtime(home, assets)
    assert target.read_text() == original
    target.write_text("[theme]\nbase = 'light'\n")
    assert prepare_runtime(home, assets).read_text() == "[theme]\nbase = 'light'\n"
    assert (assets / ".streamlit/config.toml").read_text() == original
    source_assets = tmp_path / "source"
    (source_assets / "ui").mkdir(parents=True)
    (source_assets / "ui/streamlit.toml").write_text(original)
    assert prepare_runtime(source_assets, source_assets).read_text() == original


def test_manifest_detects_tampering_missing_and_unsafe_files(tmp_path: Path) -> None:
    """Verify that manifest detects tampering missing and unsafe files.

    Args:
        tmp_path: Temporary directory supplied by pytest."""
    from dataforge.build import verify_artifacts, write_manifest

    (tmp_path / "release.whl").write_bytes(b"wheel")
    write_manifest(tmp_path, "1.2.3", [tmp_path / "release.whl"], "python")
    assert verify_artifacts(tmp_path)["version"] == "1.2.3"
    (tmp_path / "release.whl").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Checksum"):
        verify_artifacts(tmp_path)
    (tmp_path / "release.whl").unlink()
    with pytest.raises(ValueError, match="Missing"):
        verify_artifacts(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["artifacts"][0]["path"] = "../outside"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Unsafe"):
        verify_artifacts(tmp_path)


def test_build_environment_does_not_inherit_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that build environment does not inherit credentials.

    Args:
        monkeypatch: Pytest fixture for isolating environment and attribute changes."""
    from dataforge.build import build_environment

    monkeypatch.setenv("OMNIROUTE_API_KEY", "dummy-secret")
    monkeypatch.setenv("DATAFORGE_MCP_TOKEN", "dummy-token")
    monkeypatch.setenv("DATAFORGE_HOME", "/private/data")
    monkeypatch.setenv("CUSTOM_SECRET", "dummy-custom")
    env = build_environment()
    assert "PATH" in {key.upper() for key in env}
    assert not any(key in env for key in ("OMNIROUTE_API_KEY", "DATAFORGE_MCP_TOKEN", "DATAFORGE_HOME", "CUSTOM_SECRET"))


def test_wheel_assets_exclude_secret_and_runtime_canaries(tmp_path: Path) -> None:
    """Verify that wheel assets exclude secret and runtime canaries.

    Args:
        tmp_path: Temporary directory supplied by pytest."""
    root = Path(__file__).resolve().parents[1]
    for name in ("pyproject.toml", "README.md", "app.py", "dependency-overrides.txt"):
        shutil.copyfile(root / name, tmp_path / name)
    for folder in ("src/dataforge", "ui", "prompts", ".streamlit"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts/build").mkdir(parents=True)
    shutil.copyfile(root / "scripts/build/hatch_assets.py", tmp_path / "scripts/build/hatch_assets.py")
    for name in ('frozen_entry.py', 'build_executable.py', 'smoke.py', 'smoke_docker.py',
                 'windows.iss', 'windows_installer.ps1', 'sign_windows.ps1', 'smoke_installer.py'):
        shutil.copyfile(root / 'scripts/build' / name, tmp_path / 'scripts/build' / name)
    (tmp_path / "src/dataforge/__init__.py").write_text("")
    (tmp_path / "ui/__init__.py").write_text("")
    shutil.copyfile(root / "ui/style.css", tmp_path / "ui/style.css")
    (tmp_path / "prompts/prompt.md").write_text("packaged prompt")
    shutil.copyfile(root / "ui/streamlit.toml", tmp_path / "ui/streamlit.toml")
    for name in ("ui/.env", "ui/secrets.toml", "ui/cache.duckdb", ".streamlit/secrets.toml", "src/dataforge/.env"):
        (tmp_path / name).write_text("DUMMY_PACKAGING_SECRET_CANARY")
    subprocess.run(["uv", "build", "--out-dir", "dist"], cwd=tmp_path,
                   check=True, capture_output=True, text=True, timeout=60)
    with zipfile.ZipFile(next((tmp_path / "dist").glob("*.whl"))) as wheel:
        names = wheel.namelist()
        assert "dataforge/_app/app.py" in names
        assert "dataforge/_app/.streamlit/config.toml" in names
        assert wheel.read("dataforge/_app/ui/style.css") == (root / "ui/style.css").read_bytes()
        assert "dataforge/prompts/prompt.md" in names
        assert wheel.read('dataforge/dependency-overrides.txt') == (root / 'dependency-overrides.txt').read_bytes()
        assert not any(b"DUMMY_PACKAGING_SECRET_CANARY" in wheel.read(name) for name in names)
    with tarfile.open(next((tmp_path / "dist").glob("*.tar.gz"))) as archive:
        for member in archive.getmembers():
            if member.isfile():
                assert b"DUMMY_PACKAGING_SECRET_CANARY" not in archive.extractfile(member).read()


def test_source_distribution_includes_release_toolkit_and_compose(tmp_path: Path) -> None:
    """Verify that source distribution includes release toolkit and compose.

    Args:
        tmp_path: Temporary directory supplied by pytest."""
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['uv', 'build', '--sdist', '--out-dir', str(tmp_path)], cwd=root,
                   check=True, capture_output=True, text=True, timeout=60)
    with tarfile.open(next(tmp_path.glob('*.tar.gz'))) as archive:
        names = archive.getnames()
        for name in names:
            relative = Path(name).parts[1:]
            assert not any(part in {"plans", ".codex", "AGENTS.md", "KNOWLEDGE.md", ".kbignore"}
                           for part in relative), name
        for expected in ('ui/streamlit.toml', 'dependency-overrides.txt', 'compose.yaml', 'scripts/build/frozen_entry.py', 'scripts/build/smoke.py',
                         'scripts/build/smoke_docker.py', 'scripts/build/build_executable.py',
                         'scripts/build/windows.iss', 'scripts/build/windows_installer.ps1',
                         'scripts/build/sign_windows.ps1', 'scripts/build/smoke_installer.py'):
            assert any(name.endswith('/' + expected) for name in names), expected
