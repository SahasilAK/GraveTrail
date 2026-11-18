"""Distribution boundaries: writable homes, immutable assets and artifact integrity."""
import json
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest


def test_installed_home_is_outside_package_and_honors_os_conventions(tmp_path: Path) -> None:
    """Verify that installed home is outside package and honors os conventions.

    Args:
        tmp_path: Temporary directory supplied by pytest."""
    from dataforge.launcher import default_home

    assert default_home(source=False, platform="win32", environ={"LOCALAPPDATA": str(tmp_path)}) == tmp_path / "DataForge"
    assert default_home(source=False, platform="linux", environ={"XDG_DATA_HOME": str(tmp_path)}) == tmp_path / "dataforge"
    assert default_home(source=False, platform="darwin", environ={"HOME": str(tmp_path)}) == tmp_path / "Library/Application Support/DataForge"
    assert default_home(source=True, environ={}) == Path.cwd() / ".dataforge"


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
    for folder in ("src/dataforge", "ui", "prompts", ".streamlit", "tests/sample_data"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    sample = "tests/sample_data/dataforge_sql_lineage_test_project.zip"
    shutil.copyfile(root / sample, tmp_path / sample)
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
        assert wheel.read(f"dataforge/_app/{sample}") == (root / sample).read_bytes()
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
            assert not any(part in {"plans", "superpowers", ".codex", "AGENTS.md", "KNOWLEDGE.md", ".kbignore"}
                           for part in relative), name
        for expected in ('ui/streamlit.toml', 'dependency-overrides.txt', 'compose.yaml', 'scripts/build/frozen_entry.py', 'scripts/build/smoke.py',
                         'scripts/build/smoke_docker.py', 'scripts/build/build_executable.py',
                         'scripts/build/windows.iss', 'scripts/build/windows_installer.ps1',
                         'scripts/build/sign_windows.ps1', 'scripts/build/smoke_installer.py',
                         'tests/sample_data/dataforge_sql_lineage_test_project.zip'):
            assert any(name.endswith('/' + expected) for name in names), expected
