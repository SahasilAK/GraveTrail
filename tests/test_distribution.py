"""Distribution boundaries: writable homes, immutable assets and artifact integrity."""
import json
import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest


def test_gravetrail_distribution_keeps_legacy_entry_points():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "gravetrail"
    for suffix in ("", "-ui", "-build"):
        assert project["scripts"]["gravetrail" + suffix] == project["scripts"]["dataforge" + suffix]


def test_python_build_ignores_previous_brand_and_version_artifacts(tmp_path, monkeypatch):
    from dataforge.build import build_python

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    output = tmp_path / "dist"
    folder = output / "python"
    folder.mkdir(parents=True)
    for name in ("dataforge_engineering_hub-1.2.3-py3-none-any.whl", "gravetrail-1.2.2-py3-none-any.whl",
                 "gravetrail-1.2.2.tar.gz", "gravetrail-1.2.3-py3-none-any.whl", "gravetrail-1.2.3.tar.gz"):
        (folder / name).write_bytes(b"artifact")
    monkeypatch.setattr("dataforge.build._run", lambda *args, **kwargs: None)
    assert {p.name for p in build_python(tmp_path, output)} == {
        "gravetrail-1.2.3-py3-none-any.whl", "gravetrail-1.2.3.tar.gz"}
    (folder / "gravetrail-1.2.3-py3-none-any.whl").unlink()
    with pytest.raises(ValueError, match="current GraveTrail"):
        build_python(tmp_path, output)


def test_installed_home_is_outside_package_and_honors_os_conventions(tmp_path):
    from dataforge.launcher import default_home

    assert default_home(source=False, platform="win32", environ={"LOCALAPPDATA": str(tmp_path)}) == tmp_path / "DataForge"
    assert default_home(source=False, platform="linux", environ={"XDG_DATA_HOME": str(tmp_path)}) == tmp_path / "dataforge"
    assert default_home(source=False, platform="darwin", environ={"HOME": str(tmp_path)}) == tmp_path / "Library/Application Support/DataForge"
    assert default_home(source=True, environ={}) == Path.cwd() / ".dataforge"


def test_runtime_theme_is_copied_once_and_package_is_unchanged(tmp_path):
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


def test_manifest_detects_tampering_missing_and_unsafe_files(tmp_path):
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


def test_build_environment_does_not_inherit_credentials(monkeypatch):
    from dataforge.build import build_environment

    monkeypatch.setenv("OMNIROUTE_API_KEY", "dummy-secret")
    monkeypatch.setenv("DATAFORGE_MCP_TOKEN", "dummy-token")
    monkeypatch.setenv("DATAFORGE_HOME", "/private/data")
    monkeypatch.setenv("CUSTOM_SECRET", "dummy-custom")
    env = build_environment()
    assert "PATH" in {key.upper() for key in env}
    assert not any(key in env for key in ("OMNIROUTE_API_KEY", "DATAFORGE_MCP_TOKEN", "DATAFORGE_HOME", "CUSTOM_SECRET"))


def test_wheel_assets_exclude_secret_and_runtime_canaries(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for name in ("pyproject.toml", "README.md", "app.py"):
        shutil.copyfile(root / name, tmp_path / name)
    for folder in ("src/dataforge", "ui", "prompts", ".streamlit"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts/build").mkdir(parents=True)
    shutil.copyfile(root / "scripts/build/hatch_assets.py", tmp_path / "scripts/build/hatch_assets.py")
    for name in ('frozen_entry.py', 'build_executable.py', 'smoke.py', 'smoke_docker.py'):
        shutil.copyfile(root / 'scripts/build' / name, tmp_path / 'scripts/build' / name)
    (tmp_path / "src/dataforge/__init__.py").write_text("")
    (tmp_path / "ui/__init__.py").write_text("")
    (tmp_path / "prompts/prompt.md").write_text("packaged prompt")
    shutil.copyfile(root / ".streamlit/config.toml", tmp_path / ".streamlit/config.toml")
    for name in ("ui/.env", "ui/secrets.toml", "ui/cache.duckdb", ".streamlit/secrets.toml", "src/dataforge/.env"):
        (tmp_path / name).write_text("DUMMY_PACKAGING_SECRET_CANARY")
    subprocess.run(["uv", "build", "--out-dir", "dist"], cwd=tmp_path,
                   check=True, capture_output=True, text=True, timeout=60)
    with zipfile.ZipFile(next((tmp_path / "dist").glob("*.whl"))) as wheel:
        names = wheel.namelist()
        assert "dataforge/_app/app.py" in names
        assert "dataforge/_app/.streamlit/config.toml" in names
        assert "dataforge/prompts/prompt.md" in names
        assert not any(b"DUMMY_PACKAGING_SECRET_CANARY" in wheel.read(name) for name in names)
    with tarfile.open(next((tmp_path / "dist").glob("*.tar.gz"))) as archive:
        for member in archive.getmembers():
            if member.isfile():
                assert b"DUMMY_PACKAGING_SECRET_CANARY" not in archive.extractfile(member).read()


def test_source_distribution_includes_release_toolkit_and_compose(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['uv', 'build', '--sdist', '--out-dir', str(tmp_path)], cwd=root,
                   check=True, capture_output=True, text=True, timeout=60)
    with tarfile.open(next(tmp_path.glob('*.tar.gz'))) as archive:
        names = archive.getnames()
        for name in names:
            relative = Path(name).parts[1:]
            assert not any(part in {"plans", ".codex", "AGENTS.md", "KNOWLEDGE.md", ".kbignore"}
                           for part in relative), name
        for expected in ('compose.yaml', 'scripts/build/frozen_entry.py', 'scripts/build/smoke.py',
                         'scripts/build/smoke_docker.py', 'scripts/build/build_executable.py'):
            assert any(name.endswith('/' + expected) for name in names), expected
