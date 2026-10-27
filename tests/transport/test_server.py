"""Exercise protocol round trips, concurrency and cancellation over pipes/TCP."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
from anyio import Path as AsyncPath
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

ROOT = Path(__file__).resolve().parents[2]
Connection = tuple[Client, Path]


async def _wait_for_event(events: Path, expected: str) -> None:
    async with asyncio.timeout(10):
        while True:
            try:
                recorded = await AsyncPath(events).read_text(encoding="utf-8")
            except FileNotFoundError:
                recorded = ""
            if expected in recorded.splitlines():
                return
            await asyncio.sleep(0.02)


async def _wait_for_http(process: asyncio.subprocess.Process, port: int, logs: Path) -> None:
    async with asyncio.timeout(20), httpx.AsyncClient(trust_env=False) as http:
        while True:
            assert process.returncode is None, await AsyncPath(logs).read_text(encoding="utf-8")
            try:
                response = await http.get(f"http://127.0.0.1:{port}/health", timeout=1)
            except httpx.ConnectError:
                await asyncio.sleep(0.05)
            else:
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "healthy"
                return


async def _stop_http(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        async with asyncio.timeout(10):
            await process.wait()
    except TimeoutError:
        process.kill()
        async with asyncio.timeout(5):
            await process.wait()
        pytest.fail("HTTP server failed to shut down within 10 seconds")


@pytest.fixture(params=["stdio", "streamable-http"])
async def connected(
    request: pytest.FixtureRequest, tmp_path: Path, unused_tcp_port: int, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Connection]:
    """Start a fresh read-only server for each scenario, then verify it exits."""
    events = tmp_path / "events.txt"
    logs = tmp_path / "server.log"
    # A developer's credentials, proxies and .env must never influence these tests.
    for key in tuple(os.environ):
        if key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}:
            monkeypatch.delenv(key)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("INFRAHUB") and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}
    }
    env.update(
        {
            "INFRAHUB_MCP_ENV_FILE": "",
            "INFRAHUB_MCP_AUTH_MODE": "none",
            "INFRAHUB_MCP_READ_ONLY": "true",
            "INFRAHUB_ADDRESS": "http://127.0.0.1:9",
            "INFRAHUB_API_TOKEN": "transport-test-placeholder",
            "MCP_TEST_EVENTS": str(events),
        }
    )
    args = ["-m", "tests.transport._server", "--transport", request.param]
    process: asyncio.subprocess.Process | None = None
    with logs.open("w", encoding="utf-8") as output:
        transport: StdioTransport | StreamableHttpTransport
        if request.param == "stdio":
            transport = StdioTransport(
                command=sys.executable, args=args, env=env, cwd=str(ROOT), keep_alive=False, log_file=output
            )
        else:
            args.extend(["--host", "127.0.0.1", "--port", str(unused_tcp_port)])
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                *args,
                env=env,
                cwd=ROOT,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=output,
                stderr=output,
            )
            transport = StreamableHttpTransport(f"http://127.0.0.1:{unused_tcp_port}/mcp")
        try:
            if process is not None:
                await _wait_for_http(process, unused_tcp_port, logs)
            async with Client(transport, timeout=5, init_timeout=15) as client:
                yield client, events
        finally:
            if process is not None:
                await _stop_http(process)
            try:
                await _wait_for_event(events, "server-exited")
            except TimeoutError:
                pytest.fail(f"Server did not exit cleanly. Logs:\n{await AsyncPath(logs).read_text(encoding='utf-8')}")
            pid = int((await AsyncPath(events).read_text(encoding="utf-8")).splitlines()[0].split(":")[1])
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
            log_text = await AsyncPath(logs).read_text(encoding="utf-8")
            assert "Attempted to exit cancel scope" not in log_text, log_text
            assert "Task was destroyed" not in log_text, log_text


async def test_protocol_round_trip(connected: Connection) -> None:
    """A client can discover and use the read-only MCP surface over the wire."""
    client, _ = connected
    tools = {tool.name for tool in await client.list_tools()}
    assert {"get_schema", "get_session_info", "query_graphql"} <= tools
    assert "node_delete" not in tools
    result = await client.call_tool("get_schema", {})
    assert json.loads(result.content[0].text) == {"TestWidget": "Widget"}  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    resource = await client.read_resource("infrahub://schema")
    assert json.loads(resource[0].text) == {"TestWidget": "Widget"}  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    session = await client.call_tool("get_session_info", {})
    assert session.data["has_session_branch"] is False
    prompt = await client.get_prompt("answer_infra_question", {"question": "List widgets"})
    assert "List widgets" in prompt.messages[0].content.text  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]


async def test_concurrent_requests_keep_responses_separate(connected: Connection) -> None:
    """Overlapping calls return the response belonging to each request."""
    client, _ = connected
    branches = [f"request-{index}" for index in range(12)]
    results = await asyncio.gather(*(client.call_tool("get_schema", {"branch": branch}) for branch in branches))
    assert [json.loads(result.content[0].text) for result in results] == [  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
        {"TestWidget": branch} for branch in branches
    ]


async def test_cancel_cleans_server_work_and_session_remains_usable(connected: Connection) -> None:
    """Cancellation reaches the server and leaves the same session usable."""
    client, events = connected
    task = asyncio.create_task(client.call_tool("get_schema", {"branch": "slow"}, timeout=30))
    try:
        await _wait_for_event(events, "slow-started")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await _wait_for_event(events, "slow-cleaned")
        result = await client.call_tool("get_schema", {})
        assert json.loads(result.content[0].text) == {"TestWidget": "Widget"}  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
