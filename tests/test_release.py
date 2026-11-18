"""Release inputs and downloaded builds must fail closed before publication."""
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from dataforge.build import verify_artifacts, write_manifest


def test_release_version_is_independent_of_project_and_rejects_unsafe_input(tmp_path: Path) -> None:
    """Verify that release version is independent of project and rejects unsafe input.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from scripts.release import validate_version

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    assert validate_version(tmp_path, "1.2.3") == "1.2.3"
    assert validate_version(tmp_path, "1.2.4") == "1.2.4"
    for version in ("v1.2.3", "01.2.3", "1.2", "1.2.3\n", "$(whoami)", "../1.2.3"):
        with pytest.raises(ValueError):
            validate_version(tmp_path, version)


def test_windows_release_accepts_explicit_download_directory_and_keeps_installer(tmp_path: Path) -> None:
    """Verify that windows release accepts explicit download directory and keeps installer.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    import json

    from scripts.release import stage_assets

    native_builds(tmp_path / "downloads")
    windows = tmp_path / "downloads/gravetrail-Windows-X64"
    installer = windows / "gravetrail-1.2.3-windows-amd64-setup-unsigned.exe"
    installer.write_bytes(b"installer")
    evidence = windows / "windows-verification.json"
    evidence.write_text(json.dumps({"version": "1.2.3", "source_revision": "a" * 40,
                                   "mode": "development", "signing_status": "unsigned",
                                   "platform": "windows", "architecture": "amd64",
                                   "installer": installer.name, "lifecycle_verified": True}))
    write_manifest(windows, "1.2.3", [installer, evidence], "executable")
    stage_assets(windows, tmp_path / "release", "1.2.3", windows_only=True, source_revision="a" * 40)
    manifest = verify_artifacts(tmp_path / "release")
    assert len(manifest["artifacts"]) == 3
    assert manifest["windows"]["signing_status"] == "unsigned"
    assert manifest["source_revision"] == "a" * 40
    with pytest.raises(ValueError, match="production"):
        stage_assets(windows, tmp_path / "production", "1.2.3", windows_only=True,
                     mode="production", source_revision="a" * 40)
    installer.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Checksum"):
        stage_assets(windows, tmp_path / "tampered", "1.2.3", windows_only=True)


def test_materialized_version_updates_project_and_lock_without_dependency_changes(tmp_path: Path) -> None:
    """Verify that materialized version updates project and lock without dependency changes.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    import shutil
    import tomllib
    from pathlib import Path

    from scripts.release import materialize_version

    root = Path(__file__).resolve().parents[1]
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copyfile(root / name, tmp_path / name)
    before = tomllib.loads((tmp_path / "uv.lock").read_text())
    materialize_version(tmp_path, "2.3.4")
    project = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    after = tomllib.loads((tmp_path / "uv.lock").read_text())
    assert project["project"]["version"] == "2.3.4"
    assert next(p for p in after["package"] if p["name"] == "gravetrail")["version"] == "2.3.4"
    assert [p for p in before["package"] if p["name"] != "gravetrail"] == [
        p for p in after["package"] if p["name"] != "gravetrail"]


def native_builds(root: Any, version: Any="1.2.3") -> None:
    """Handle native builds for the test scenario.

    Args:
        root: Root value used by the test case.
        version: Version value used by the test case.
    """
    for runner, platform, extension in (("Windows-X64", "windows-amd64", ".zip"),
                                         ("Linux-X64", "linux-x86_64", ".tar.gz"),
                                         ("macOS-ARM64", "darwin-arm64", ".tar.gz")):
        directory = root / f"gravetrail-{runner}"
        directory.mkdir(parents=True)
        archive = directory / f"gravetrail-{version}-{platform}{extension}"
        archive.write_bytes(runner.encode())
        python = directory / "python/package.whl"
        python.parent.mkdir()
        python.write_bytes(b"wheel")
        write_manifest(directory, version, [archive, python], "executable")


def test_stage_verifies_each_build_and_publishes_only_standalone_archives(tmp_path: Path) -> None:
    """Verify that stage verifies each build and publishes only standalone archives.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from scripts.release import stage_assets

    downloads, output = tmp_path / "downloads", tmp_path / "release"
    native_builds(downloads)
    stage_assets(downloads, output, "1.2.3")
    manifest = verify_artifacts(output)
    assert manifest["version"] == "1.2.3"
    assert len(manifest["artifacts"]) == 3
    assert len(list(output.iterdir())) == 5
    assert not list(output.rglob("*.whl"))
    assert all(item["path"].startswith("gravetrail-1.2.3-") for item in manifest["artifacts"])
    with pytest.raises(FileExistsError):
        stage_assets(downloads, output, "1.2.3")
    assert verify_artifacts(output) == manifest


@pytest.mark.parametrize("problem", ["version", "duplicate"])
def test_stage_rejects_incomplete_or_inconsistent_downloads(tmp_path: Path, problem: str) -> None:
    """Verify that stage rejects incomplete or inconsistent downloads.

    Args:
        tmp_path: Temporary directory supplied by pytest.
        problem: Problem value used by the test case.
    """
    from scripts.release import stage_assets

    downloads, output = tmp_path / "downloads", tmp_path / "release"
    native_builds(downloads)
    windows = downloads / "gravetrail-Windows-X64"
    archive = next(windows.glob("*.zip"))
    if problem == "version":
        write_manifest(windows, "2.0.0", [archive], "executable")
    else:
        import shutil
        shutil.copytree(windows, downloads / "gravetrail-Windows-ARM64")
    with pytest.raises((ValueError, FileNotFoundError)):
        stage_assets(downloads, output, "1.2.3")
    assert not output.exists(), "Validate every build before copying release assets"


def release_policy(tmp_path, *, mode=None, ref='refs/heads/main', dry_run='true', signing=None):
    """Execute the workflow's actual preflight Bash without builds or GitHub writes."""
    import yaml

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.load((root / '.github/workflows/publish-release.yml').read_text(), Loader=yaml.BaseLoader)
    policy = next((step for step in workflow['jobs']['prepare']['steps'] if step.get('id') == 'policy'), None)
    assert policy is not None, 'Release mode must be validated before resolving versions or building'
    default = workflow['on']['workflow_dispatch']['inputs']['release_mode']['default']
    output = tmp_path / 'output'
    summary = tmp_path / 'summary'
    environment = dict(os.environ, RELEASE_MODE=mode or default, GITHUB_REF=ref, DEFAULT_BRANCH='main',
                       DRY_RUN=dry_run, GITHUB_OUTPUT=output.as_posix(), GITHUB_STEP_SUMMARY=summary.as_posix(),
                       WINDOWS_SIGNING_THUMBPRINT='', WINDOWS_TIMESTAMP_URL='', WINDOWS_PUBLISHER='')
    environment.update(signing or {})
    bash = (str(Path(shutil.which('git')).resolve().parents[1] / 'bin/bash.exe') if sys.platform == 'win32'
            else shutil.which('bash'))
    result = subprocess.run([bash, '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', policy['run']],
                            env=environment, cwd=tmp_path, capture_output=True, text=True, timeout=15)
    return result, output.read_text() if output.exists() else '', summary.read_text() if summary.exists() else ''


def test_production_publish_remains_unsigned(tmp_path):
    result, output, _ = release_policy(tmp_path, mode='production', dry_run='false')
    assert result.returncode == 0, result.stdout + result.stderr
    assert output == 'build_mode=development\n'


def test_production_release_rejects_wrong_branch(tmp_path):
    result, output, _ = release_policy(tmp_path, mode='production', ref='refs/heads/feature')
    assert result.returncode != 0
    assert output == ''
