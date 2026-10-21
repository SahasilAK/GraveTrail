"""Test an actual image with a disposable volume; never touches existing containers/data."""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import subprocess
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from smoke import check_mcp, render_session

from dataforge.build import build_environment


def main() -> None:
    """Verify the Docker image's lineage, UI, volume persistence, and MCP flows."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="gravetrail:0.1.0")
    args = parser.parse_args()
    name = "gravetrail-smoke-" + uuid.uuid4().hex[:12]
    env = build_environment()

    def docker(*arguments: str, capture: bool = True) -> str:
        """Run a Docker CLI command using the smoke-test environment.

        Args:
            *arguments: Docker subcommand and arguments.
            capture: Whether to capture standard output.

        Returns:
            Captured standard output, or an empty string when capture is disabled.
        """
        process = subprocess.run(["docker", *arguments], env=env, check=True, text=True,
                                 stdout=subprocess.PIPE if capture else None, timeout=180)
        return process.stdout.strip() if capture else ""

    docker("volume", "create", name)
    try:
        with tempfile.TemporaryDirectory(prefix="gravetrail-container-") as temporary:
            inputs = Path(temporary)
            (inputs / "flow.sql").write_text("create table pub.kpi as select id from raw.orders;", encoding="utf-8")
            runtime = ["run", "--rm", "-v", f"{name}:/data", "-v", f"{inputs}:/imports:ro", args.image]
            assert docker(*runtime, "id", "-u") == "10001"

            def cli(*arguments: str) -> dict[str, Any]:
                """Run a JSON CLI command inside the test container.

                Args:
                    *arguments: Application CLI subcommand and arguments.

                Returns:
                    Decoded JSON response from the command.
                """
                return json.loads(docker(*runtime, "gravetrail", "--json", "--allow-write",
                                         "--allowed-root", "/imports", *arguments))

            workspace = cli("workspace", "create", "Container persistence")["workspace_id"]
            assert cli("ingest", "/imports", "--workspace", workspace)["result"]["accepted"] == 1
            cli("lineage", "build", "--workspace", workspace)
            assert cli("lineage", "upstream", "pub.kpi", "--workspace", workspace)["items"][0]["name"] == "raw.orders"
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            docker("run", "-d", "--name", name, "-v", f"{name}:/data", "-p",
                   f"127.0.0.1:{port}:8501", args.image)
            try:
                for _ in range(90):
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                            assert response.read() == b"ok"
                        break
                    except OSError:
                        time.sleep(1)
                else:
                    raise RuntimeError(docker("logs", name))
                asyncio.run(render_session(port))
            finally:
                docker("stop", "--time", "15", name)
                docker("rm", name)
            assert cli("workspace", "list")["items"][0]["name"] == "Container persistence"
            asyncio.run(check_mcp(["docker", "run", "--rm", "-i", "-v", f"{name}:/data",
                                   args.image, "gravetrail"], inputs, env))
        print("PASS: non-root container, import/lineage, rendered UI, volume persistence and stdio MCP query")
    finally:
        subprocess.run(["docker", "rm", "-f", name], env=env, capture_output=True, timeout=30)
        docker("volume", "rm", name)


if __name__ == "__main__":
    main()
