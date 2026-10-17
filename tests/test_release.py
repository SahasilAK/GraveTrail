"""Release inputs and downloaded builds must fail closed before publication."""
import subprocess

import pytest

from dataforge.build import verify_artifacts, write_manifest


def test_release_version_matches_project_and_rejects_unsafe_input(tmp_path):
    from scripts.release import validate_version

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    assert validate_version(tmp_path, "1.2.3") == "1.2.3"
    for version in ("1.2.4", "v1.2.3", "01.2.3", "1.2", "1.2.3\n", "$(whoami)", "../1.2.3"):
        with pytest.raises(ValueError):
            validate_version(tmp_path, version)


def native_builds(root, version="1.2.3"):
    for runner, platform, extension in (("Windows-X64", "windows-amd64", ".zip"),
                                         ("Linux-X64", "linux-x86_64", ".tar.gz"),
                                         ("macOS-ARM64", "darwin-arm64", ".tar.gz")):
        directory = root / f"dataforge-{runner}"
        directory.mkdir(parents=True)
        archive = directory / f"dataforge-{version}-{platform}{extension}"
        archive.write_bytes(runner.encode())
        python = directory / "python/package.whl"
        python.parent.mkdir()
        python.write_bytes(b"wheel")
        write_manifest(directory, version, [archive, python], "executable")


def test_stage_verifies_each_build_and_publishes_only_standalone_archives(tmp_path):
    from scripts.release import stage_assets

    downloads, output = tmp_path / "downloads", tmp_path / "release"
    native_builds(downloads)
    stage_assets(downloads, output, "1.2.3")
    manifest = verify_artifacts(output)
    assert manifest["version"] == "1.2.3"
    assert len(manifest["artifacts"]) == 3
    assert len(list(output.iterdir())) == 5
    assert not list(output.rglob("*.whl"))
    assert all(item["path"].startswith("dataforge-1.2.3-") for item in manifest["artifacts"])


@pytest.mark.parametrize("problem", ["missing", "tampered", "version", "duplicate", "unlisted"])
def test_stage_rejects_incomplete_or_inconsistent_downloads(tmp_path, problem):
    from scripts.release import stage_assets

    downloads, output = tmp_path / "downloads", tmp_path / "release"
    native_builds(downloads)
    windows = downloads / "dataforge-Windows-X64"
    archive = next(windows.glob("*.zip"))
    if problem == "missing":
        (windows / "manifest.json").unlink()
    elif problem == "tampered":
        archive.write_bytes(b"changed")
    elif problem == "version":
        write_manifest(windows, "2.0.0", [archive], "executable")
    elif problem == "duplicate":
        import shutil
        shutil.copytree(windows, downloads / "dataforge-Windows-ARM64")
    else:
        (windows / "manifest.json").unlink()
        write_manifest(windows, "1.2.3", [windows / "python/package.whl"], "executable")
    with pytest.raises((ValueError, FileNotFoundError)):
        stage_assets(downloads, output, "1.2.3")
    assert not output.exists(), "Validate every build before copying release assets"


def test_stage_refuses_existing_output(tmp_path):
    from scripts.release import stage_assets

    native_builds(tmp_path / "downloads")
    output = tmp_path / "release"
    output.mkdir()
    (output / "keep.txt").write_text("existing")
    with pytest.raises(FileExistsError):
        stage_assets(tmp_path / "downloads", output, "1.2.3")
    assert (output / "keep.txt").read_text() == "existing"


def test_copilot_notes_use_only_supplied_context_and_fall_back_on_failure(monkeypatch):
    from scripts.release import copilot_summary

    calls = []

    def run(command, **kwargs):
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
        def fail(*args, **kwargs):
            raise error
        monkeypatch.setattr(subprocess, "run", fail)
        assert copilot_summary("notes", "commits") is None


def test_release_notes_always_retain_changes_and_installation_guidance():
    from scripts.release import release_notes

    for summary in (None, "## Highlights\n\n- Export fix."):
        notes = release_notes("## What's Changed\nPR #7", "abc123 fix: export", summary)
        assert "PR #7" in notes and "abc123 fix: export" in notes
        assert "SHA256SUMS" in notes and "dataforge.exe" in notes
        assert ("AI-generated" in notes) == bool(summary)
