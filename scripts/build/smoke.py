"""Exercise installed/frozen CLI, lineage, stdio MCP and a rendered Streamlit session."""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from dataforge.build import build_environment


async def render_session(port: int) -> None:
    from streamlit.proto.BackMsg_pb2 import BackMsg
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    from websockets.asyncio.client import connect

    connection = await connect(f"ws://127.0.0.1:{port}/_stcore/stream",
                               origin=f"http://127.0.0.1:{port}", subprotocols=["streamlit"])
    request = BackMsg()
    request.rerun_script.query_string = ""
    await connection.send(request.SerializeToString())
    seen_delta = False
    try:
        while True:
            raw = await asyncio.wait_for(connection.recv(), timeout=60)
            if raw is None:
                raise RuntimeError("UI session closed before rendering")
            message = ForwardMsg.FromString(raw)
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
                return
    finally:
        await connection.close()


async def check_mcp(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(command=command[0], args=[*command[1:], "mcp"],
                                       cwd=str(cwd), env=env)
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            if not any(tool.name == "list_workspaces" for tool in tools.tools):
                raise RuntimeError("MCP did not register workspace tools")
            result = await session.call_tool("list_workspaces", {})
            if result.isError:
                raise RuntimeError("MCP workspace query failed")


def main() -> None:
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
    with tempfile.TemporaryDirectory(prefix="dataforge-distribution-") as temporary:
        cwd = Path(temporary)
        env = {**build_environment(), "DATAFORGE_HOME": str(cwd / "home")}
        inputs = cwd / "inputs"
        inputs.mkdir()
        (inputs / "flow.sql").write_text("create table pub.kpi as select id from raw.orders;", encoding="utf-8")
        flags = ["--json", "--allow-write", "--allowed-root", str(inputs)]

        def run(*arguments):
            process = subprocess.run([*cli, *flags, *arguments], cwd=cwd, env=env,
                                     capture_output=True, text=True, timeout=90, check=True)
            return json.loads(process.stdout)

        workspace = run("workspace", "create", "Distribution smoke")["workspace_id"]
        assert run("ingest", str(inputs), "--workspace", workspace)["result"]["accepted"] == 1
        run("lineage", "build", "--workspace", workspace)
        found = run("lineage", "upstream", "pub.kpi", "--workspace", workspace)
        assert found["items"][0]["name"] == "raw.orders"
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
        print("PASS: installed CLI import/lineage, stdio MCP query, UI health and rendered session")


if __name__ == "__main__":
    main()
