"""Release inputs and downloaded builds must fail closed before publication."""
import subprocess
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


@pytest.mark.parametrize("bump,expected", [("major", "3.0.0"), ("minor", "2.5.0"), ("patch", "2.4.10")])
def test_resolve_version_uses_highest_published_stable_release(bump: str, expected: str) -> None:
    """Verify that resolve version uses highest published stable release.

    Args:
        bump: Bump value used by the test case.
        expected: Expected result for the test case.
    """
    from scripts.release import resolve_version

    releases = [{"tag_name": tag, "draft": draft, "prerelease": pre}
                for tag, draft, pre in [("v2.4.9", False, False), ("v1.9.0", False, False),
                                        ("v9.0.0", True, False), ("v8.0.0-rc1", False, True)]]
    assert resolve_version(releases, bump=bump) == expected
    assert resolve_version([], bump="patch") == "0.0.1"
    assert resolve_version(releases, exact="3.2.1", bump="patch") == "3.2.1"
    for exact in ("1.0.0", "2.4.9", "v3.0.0"):
        with pytest.raises(ValueError):
            resolve_version(releases, exact=exact)
    with pytest.raises(ValueError):
        resolve_version([], bump="wat")


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


@pytest.mark.parametrize("problem", ["missing", "tampered", "version", "duplicate", "unlisted"])
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
    if problem == "missing":
        (windows / "manifest.json").unlink()
    elif problem == "tampered":
        archive.write_bytes(b"changed")
    elif problem == "version":
        write_manifest(windows, "2.0.0", [archive], "executable")
    elif problem == "duplicate":
        import shutil
        shutil.copytree(windows, downloads / "gravetrail-Windows-ARM64")
    else:
        (windows / "manifest.json").unlink()
        write_manifest(windows, "1.2.3", [windows / "python/package.whl"], "executable")
    with pytest.raises((ValueError, FileNotFoundError)):
        stage_assets(downloads, output, "1.2.3")
    assert not output.exists(), "Validate every build before copying release assets"


def test_stage_refuses_existing_output(tmp_path: Path) -> None:
    """Verify that stage refuses existing output.

    Args:
        tmp_path: Temporary directory supplied by pytest.
    """
    from scripts.release import stage_assets

    native_builds(tmp_path / "downloads")
    output = tmp_path / "release"
    output.mkdir()
    (output / "keep.txt").write_text("existing")
    with pytest.raises(FileExistsError):
        stage_assets(tmp_path / "downloads", output, "1.2.3")
    assert (output / "keep.txt").read_text() == "existing"


def test_copilot_notes_use_only_supplied_context_and_fall_back_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that copilot notes use only supplied context and fall back on failure.

    Args:
        monkeypatch: Pytest fixture for isolating environment and attribute changes.

    Raises:
        error: Raised by the test helper.
    """
    from scripts.release import copilot_summary

    calls = []

    def run(command: Any, **kwargs: Any) -> Any:
        """Handle run for the test scenario.

        Args:
            command: Command value used by the test case.
            kwargs: Keyword arguments forwarded to the operation.

        Returns:
            Value produced for the test scenario.
        """
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "## Highlights\n\n- Fix lineage export.\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert "Fix lineage" in copilot_summary("GitHub notes", "abc123 fix: export")
    command, kwargs = calls[0]
    assert "--available-tools=" in command
    assert "--disable-builtin-mcps" in command
    assert "--no-custom-instructions" in command
    assert "abc123 fix: export" in command[-1]
    assert kwargs["timeout"] == 90
    assert kwargs["stdin"] == subprocess.DEVNULL

    for error in (FileNotFoundError(), subprocess.CalledProcessError(1, command),
                  subprocess.TimeoutExpired(command, 90)):
        def fail(*args: Any, **kwargs: Any) -> None:
            """Raise the injected failure used by the test.

            Args:
                args: Positional arguments forwarded to the operation.
                kwargs: Keyword arguments forwarded to the operation.

            Raises:
                error: Raised by the test helper.
            """
            raise error
        monkeypatch.setattr(subprocess, "run", fail)
        assert copilot_summary("notes", "commits") is None


def test_release_notes_always_retain_changes_and_installation_guidance() -> None:
    """Verify that release notes always retain changes and installation guidance."""
    from scripts.release import release_notes

    for summary in (None, "## Highlights\n\n- Export fix."):
        notes = release_notes("## What's Changed\nPR #7", "abc123 fix: export", summary)
        assert "PR #7" in notes and "abc123 fix: export" in notes
        assert "SHA256SUMS" in notes and "gravetrail.exe" in notes
        assert ("AI-generated" in notes) == bool(summary)


def test_standalone_release_test_gate_fetches_inventory_history() -> None:
    """The reusable release test job needs the pinned documentation baseline."""
    import yaml

    workflows = Path(__file__).resolve().parents[1] / ".github/workflows"
    publisher = yaml.safe_load((workflows / "publish-release.yml").read_text(encoding="utf-8"))
    assert publisher["jobs"]["builds"]["uses"] == "./.github/workflows/release.yml"
    release = yaml.safe_load((workflows / "release.yml").read_text(encoding="utf-8"))
    steps = release["jobs"]["native"]["steps"]
    test_index = next(i for i, step in enumerate(steps) if step.get("run") == "uv run pytest -q")
    checkout = next(step for step in steps[:test_index]
                    if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout.get("with", {}).get("fetch-depth") == 0
