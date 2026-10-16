"""Host-platform release builds with locked dependencies and integrity manifests."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path


def build_environment() -> dict[str, str]:
    allowed = {"path", "systemroot", "windir", "temp", "tmp", "home", "userprofile", "localappdata",
               "appdata", "programfiles", "programfiles(x86)", "programw6432", "pathext", "comspec",
               "lang", "lc_all", "number_of_processors", "processor_architecture"}
    return {key: value for key, value in os.environ.items() if key.lower() in allowed}


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_manifest(directory: Path, version: str, artifacts: list[Path], target: str) -> Path:
    path = directory / "manifest.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    records = {item["path"]: item for item in previous.get("artifacts", [])} if previous.get("version") == version else {}
    for artifact in artifacts:
        relative = artifact.resolve().relative_to(directory.resolve()).as_posix()
        records[relative] = {"path": relative, "sha256": _digest(artifact), "bytes": artifact.stat().st_size}
    manifest = {"version": version, "target": target, "platform": platform.platform(),
                "python": platform.python_version(), "built_at": datetime.now(timezone.utc).isoformat(),
                "artifacts": sorted(records.values(), key=lambda item: item["path"])}
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (directory / "SHA256SUMS").write_text("".join(
        f"{item['sha256']}  {item['path']}\n" for item in manifest["artifacts"]), encoding="utf-8")
    return path


def verify_artifacts(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("artifacts"):
        raise ValueError("Manifest contains no artifacts")
    for item in manifest["artifacts"]:
        name = item["path"]
        target = directory / name
        if Path(name).is_absolute() or ".." in Path(name).parts or target.is_symlink():
            raise ValueError(f"Unsafe artifact path: {name}")
        if not target.resolve().is_relative_to(directory.resolve()):
            raise ValueError(f"Unsafe artifact path: {name}")
        if not target.is_file():
            raise ValueError(f"Missing artifact: {name}")
        if target.stat().st_size != item["bytes"] or _digest(target) != item["sha256"]:
            raise ValueError(f"Checksum mismatch: {name}")
    expected = "".join(f"{item['sha256']}  {item['path']}\n" for item in manifest["artifacts"])
    if (directory / "SHA256SUMS").read_text(encoding="utf-8") != expected:
        raise ValueError("Checksum list does not match manifest")
    return manifest


def _run(args: list[str], root: Path, *, capture=False) -> str:
    result = subprocess.run(args, cwd=root, env=build_environment(), check=True,
                            text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def build_python(root: Path, output: Path) -> list[Path]:
    folder = output / "python"
    _run(["uv", "build", "--out-dir", str(folder)], root)
    return sorted(folder.glob("*.whl")) + sorted(folder.glob("*.tar.gz"))


def build_docker(root: Path, output: Path, version: str) -> list[Path]:
    tag = f"dataforge:{version}"
    _run(["docker", "build", "--tag", tag, "."], root)
    details = json.loads(_run(["docker", "image", "inspect", tag], root, capture=True))[0]
    path = output / "docker-image.json"
    path.write_text(json.dumps({"tag": tag, "id": details["Id"], "architecture": details["Architecture"],
                                "os": details["Os"]}, indent=2) + "\n", encoding="utf-8")
    return [path]


def build_executable(root: Path, output: Path, version: str) -> list[Path]:
    work = output / ".build"
    work.mkdir(parents=True, exist_ok=True)
    venv = work / "venv"
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.exists():
        _run(["uv", "venv", "--python", "3.11", str(venv)], root)
    requirements = work / "requirements.txt"
    _run(["uv", "export", "--locked", "--no-dev", "--extra", "build", "--no-emit-project",
          "--output-file", str(requirements)], root, capture=True)
    _run(["uv", "pip", "sync", "--python", str(python), str(requirements)], root)
    python_artifacts = build_python(root, output)
    wheels = [p for p in python_artifacts if p.suffix == ".whl"]
    _run(["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheels[0])], root)
    assets = _run([str(python), "-c", "from dataforge.launcher import application_root; print(application_root())"],
                  root, capture=True)
    _run([str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "dataforge",
          "--distpath", str(work / "bundle"), "--workpath", str(work / "pyinstaller"),
          "--specpath", str(work), "--paths", assets, "--collect-all", "dataforge",
          "--collect-all", "streamlit", "--collect-submodules", "ui", "--collect-submodules", "sqlglot",
          "--recursive-copy-metadata", "dataforge-engineering-hub",
          str(root / "scripts/build/frozen_entry.py")], root)
    bundle = work / "bundle/dataforge"
    name = f"dataforge-{version}-{platform.system().lower()}-{platform.machine().lower()}"
    if sys.platform == "win32":
        archive = Path(shutil.make_archive(str(output / name), "zip", bundle.parent, bundle.name))
    else:
        archive = output / f"{name}.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(bundle, arcname="dataforge")
    return [*python_artifacts, archive]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["python", "docker", "executable", "all"], default="python")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)
    root, output = args.root.resolve(), args.output.resolve()
    if args.verify:
        manifest = verify_artifacts(output)
        print(f"Verified {len(manifest['artifacts'])} artifacts for {manifest['version']}")
        return
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    output.mkdir(parents=True, exist_ok=True)
    artifacts = []
    if args.target in {"python", "all"}:
        artifacts.extend(build_python(root, output))
    if args.target in {"docker", "all"}:
        artifacts.extend(build_docker(root, output, version))
    if args.target in {"executable", "all"}:
        artifacts.extend(build_executable(root, output, version))
    write_manifest(output, version, artifacts, args.target)
    verify_artifacts(output)
    print(f"Built and verified {len(artifacts)} artifacts in {output}")


if __name__ == "__main__":
    main()
