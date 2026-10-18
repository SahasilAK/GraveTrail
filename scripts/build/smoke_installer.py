"""Exercise exact final Windows installer bytes in a disposable per-user location."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from dataforge.build import build_environment, write_manifest


def smoke_installer(directory: Path, *, finalize: bool = False) -> None:
    evidence_path = directory / "windows-verification.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    installer = directory / evidence["installer"]
    script = Path(__file__).with_name("sign_windows.ps1")
    with tempfile.TemporaryDirectory(prefix="GraveTrail install é spaces ") as temporary:
        base = Path(temporary)
        install = base / "Program Files/GraveTrail"
        home = base / "persistent home"
        home.mkdir()
        (home / "settings.txt").write_text("retain user settings", encoding="utf-8")
        inputs = base / "inputs"
        inputs.mkdir()
        (inputs / "flow.sql").write_text("create table pub.kpi as select id from raw.orders;")
        env = {**build_environment(), "DATAFORGE_HOME": str(home)}

        def run(command, *, check=True, timeout=180, environment=env):
            return subprocess.run(list(map(str, command)), cwd=base, env=environment,
                                  capture_output=True, text=True, encoding="utf-8", check=check,
                                  timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)

        def setup(*, check=True):
            return run([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                        f"/DIR={install}", "/TASKS=", f"/LOG={base / 'install.log'}"], check=check)

        def verify_trust(path):
            if evidence["mode"] == "production":
                run(["pwsh", "-NoProfile", "-File", script, "-Path", path, "-VerifyOnly"],
                    environment=None)

        verify_trust(installer)
        setup()
        app = install / "gravetrail.exe"
        uninstaller = install / "unins000.exe"
        try:
            for item in evidence["payload"]:
                path = install / item["path"]
                assert path.resolve().is_relative_to(install.resolve()), "Unsafe payload path"
                with path.open("rb") as stream:
                    assert hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"], item["path"]
            verify_trust(app)
            verify_trust(uninstaller)
            cli = [app, "--cli", "--json", "--allow-write", "--allowed-root", inputs]
            workspace = json.loads(run([*cli, "workspace", "create", "Installer preservation"]).stdout)["workspace_id"]
            run([*cli, "ingest", inputs, "--workspace", workspace])
            run([*cli, "lineage", "build", "--workspace", workspace])
            original = json.loads(run([*cli, "lineage", "upstream", "pub.kpi", "--workspace", workspace]).stdout)
            assert original["items"][0]["name"] == "raw.orders"
            # Exercise the actual installer refusal while a UI owner holds the mutex.
            process = subprocess.Popen([str(app), "--no-browser", "--home", str(home), "--port", "18539"],
                                       cwd=base, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                import time

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
                kernel.OpenMutexW.restype = ctypes.c_void_p
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                for _ in range(120):
                    handle = kernel.OpenMutexW(0x00100000, False, "Local\\GraveTrail.Application")
                    if handle:
                        kernel.CloseHandle(handle)
                        break
                    assert process.poll() is None, "Installed UI exited before startup"
                    time.sleep(.25)
                else:
                    raise RuntimeError("Installed UI did not register its running-instance mutex")
                assert setup(check=False).returncode != 0, "Upgrade replaced a running application"
                assert process.poll() is None, "Installer closed the running application"
            finally:
                process.terminate()
                process.wait(timeout=30)
            setup()
            assert json.loads(run([*cli, "lineage", "upstream", "pub.kpi", "--workspace", workspace]).stdout) == original
            # Shared smoke proves actual installed SQL, MCP and rendered UI outside checkout.
            subprocess.run([sys.executable, str(Path(__file__).with_name("smoke.py")),
                            "--executable", str(app)], check=True, timeout=240)
            before = {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
        finally:
            if uninstaller.exists():
                run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        assert not app.exists(), "Uninstall left application files behind"
        assert before == {p.relative_to(home): p.read_bytes() for p in home.rglob("*") if p.is_file()}
        assert (home / "settings.txt").read_text() == "retain user settings"
    if finalize:
        evidence["lifecycle_verified"] = True
        evidence["lifecycle_checks"] = ["payload hashes", "installed CLI/MCP/UI", "running-owner refusal",
                                        "upgrade retains lineage", "uninstall retains data/settings",
                                        "paths with spaces and non-ASCII"]
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        artifacts = [*directory.glob("*.zip"), *directory.glob("*.exe"), evidence_path]
        write_manifest(directory, evidence["version"], artifacts, "executable")
    print("PASS: final installer payload, launch, running-owner refusal, upgrade and uninstall preservation")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    smoke_installer(args.directory.resolve(), finalize=args.finalize)
