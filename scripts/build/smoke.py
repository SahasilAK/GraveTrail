"""Exercise installed/frozen CLI, lineage, stdio MCP and a rendered Streamlit session."""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from dataforge.build import build_environment


async def render_session(port: int) -> None:
    """Connect to Streamlit's websocket and require a successful rendered page.

    Args:
        port: Local port where the smoke-test UI is listening.

    Raises:
        RuntimeError: If the session closes, fails to compile, or renders no page.
        asyncio.TimeoutError: If Streamlit does not respond within the session timeout.
    """
    from streamlit.proto.BackMsg_pb2 import BackMsg
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    from websockets.asyncio.client import connect

    connection = await connect(f"ws://127.0.0.1:{port}/_stcore/stream",
                               origin=f"http://127.0.0.1:{port}", subprotocols=["streamlit"])
    request = BackMsg()
    request.rerun_script.query_string = ""
    await connection.send(request.SerializeToString())
    seen_delta = False
    seen_brand = False
    try:
        while True:
            raw = await asyncio.wait_for(connection.recv(), timeout=60)
            if raw is None:
                raise RuntimeError("UI session closed before rendering")
            message = ForwardMsg.FromString(raw)
            if message.HasField("page_config_changed"):
                seen_brand = message.page_config_changed.title == "GraveTrail | Engineering workspace"
            if message.HasField("delta"):
                seen_delta = True
                if message.delta.HasField("new_element") and message.delta.new_element.HasField("exception"):
                    raise RuntimeError("UI render error: " + message.delta.new_element.exception.message)
            if message.HasField("script_finished"):
                if message.script_finished == ForwardMsg.FINISHED_WITH_COMPILE_ERROR:
                    raise RuntimeError("UI script failed to compile")
                if message.script_finished == ForwardMsg.FINISHED_EARLY_FOR_RERUN:
                    continue
                if not seen_delta:
                    raise RuntimeError("UI produced no rendered elements")
                if not seen_brand:
                    raise RuntimeError("UI did not apply the GraveTrail page title")
                return
    finally:
        await connection.close()


async def check_mcp(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    """Start an MCP stdio server and verify its workspace listing tool.

    Args:
        command: Executable and arguments used to start the application.
        cwd: Working directory for the server process.
        env: Environment passed to the server process.

    Raises:
        RuntimeError: If the server identity or workspace tool check fails.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(command=command[0], args=[*command[1:], "mcp"],
                                       cwd=str(cwd), env=env)
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            initialized = await session.initialize()
            if initialized.serverInfo.name != "GraveTrail":
                raise RuntimeError("MCP did not identify itself as GraveTrail")
            tools = await session.list_tools()
            if not any(tool.name == "list_workspaces" for tool in tools.tools):
                raise RuntimeError("MCP did not register workspace tools")
            result = await session.call_tool("list_workspaces", {})
            if result.isError:
                raise RuntimeError("MCP workspace query failed")


def main() -> None:
    """Exercise a built Python entry point or executable in disposable storage."""
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--python", type=Path)
    group.add_argument("--executable", type=Path)
    args = parser.parse_args()
    if args.executable:
        ui = [str(args.executable.resolve())]
        cli = [*ui, "--cli"]
    else:
        python = str(args.python.resolve())
        ui = [python, "-m", "dataforge.launcher"]
        cli = [python, "-m", "dataforge.cli"]
    with tempfile.TemporaryDirectory(prefix="gravetrail-distribution-") as temporary:
        cwd = Path(temporary)
        env = {**build_environment(), "DATAFORGE_HOME": str(cwd / "home")}
        inputs = cwd / "inputs"
        inputs.mkdir()
        (inputs / "flow.sql").write_text("create table pub.kpi as select id from raw.orders;", encoding="utf-8")
        flags = ["--json", "--allow-write", "--allowed-root", str(inputs)]

        def run(*arguments: str) -> dict[str, Any]:
            """Run one JSON CLI command in the disposable distribution home.

            Args:
                *arguments: CLI subcommand and arguments passed after common flags.

            Returns:
                Decoded JSON response from the command.
            """
            process = subprocess.run([*cli, *flags, *arguments], cwd=cwd, env=env,
                                     capture_output=True, text=True, timeout=90, check=True)
            return json.loads(process.stdout)

        workspace = run("workspace", "create", "Distribution smoke")["workspace_id"]
        assert run("ingest", str(inputs), "--workspace", workspace)["result"]["accepted"] == 1
        run("lineage", "build", "--workspace", workspace)
        found = run("lineage", "upstream", "pub.kpi", "--workspace", workspace)
        assert found["items"][0]["name"] == "raw.orders"
        for format in ('svg', 'png'):
            destination = cwd / ('lineage.' + format)
            result = run('export', 'graph', 'pub.kpi', '--workspace', workspace,
                         '--format', format, '--output', str(destination))
            assert result['bytes'] == destination.stat().st_size
            data = destination.read_bytes()
            if format == 'svg':
                assert ET.fromstring(data).tag == '{http://www.w3.org/2000/svg}svg'
            else:
                assert data.startswith(b'\x89PNG\r\n\x1a\n')
                width, height = struct.unpack('>II', data[16:24])
                assert 0 < width <= 8192 and 0 < height <= 8192 and width * height <= 16_000_000
        asyncio.run(check_mcp(cli, cwd, env))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with (cwd / "ui.log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen([*ui, "--no-browser", "--port", str(port)], cwd=cwd,
                                      env=env, stdout=log, stderr=log)
            try:
                for _ in range(120):
                    if server.poll() is not None:
                        raise RuntimeError((cwd / "ui.log").read_text(encoding="utf-8"))
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                            assert response.read() == b"ok"
                        break
                    except OSError:
                        time.sleep(.5)
                else:
                    raise RuntimeError("UI health timed out")
                asyncio.run(render_session(port))
            finally:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=15)
        print("PASS: installed CLI import/lineage, SVG/PNG images, stdio MCP query, UI health and rendered session")


if __name__ == "__main__":
    main()
