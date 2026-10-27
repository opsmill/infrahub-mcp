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
import toon
from anyio import Path as AsyncPath
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from mcp import MCPError

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


@pytest.fixture(params=[("stdio", "auto"), ("streamable-http", "auto")], ids=["stdio", "streamable-http"])
async def connected(
    request: pytest.FixtureRequest, tmp_path: Path, unused_tcp_port: int, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Connection]:
    """Start a fresh read-only server for each scenario, then verify it exits.

    ``request.param`` is a ``(transport, client mode)`` pair; a test can parametrize this
    fixture indirectly to pin the protocol era with ``mode="legacy"``.
    """
    transport_name, mode = request.param
    events = tmp_path / "events.txt"
    logs = tmp_path / "server.log"
    # A developer's credentials, proxies and .env must never influence these tests.
    for key in tuple(os.environ):
        if key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}:
            monkeypatch.delenv(key)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("INFRAHUB", "OTEL_"))
        and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}
    }
    env.update(
        {
            "INFRAHUB_MCP_ENV_FILE": "",
            "INFRAHUB_MCP_AUTH_MODE": "none",
            "INFRAHUB_MCP_READ_ONLY": "true",
            "INFRAHUB_MCP_OTEL_ENABLED": "true",
            "FASTMCP_TELEMETRY_MODE": "native",
            "INFRAHUB_ADDRESS": "http://127.0.0.1:9",
            "INFRAHUB_API_TOKEN": "transport-test-placeholder",
            "MCP_TEST_EVENTS": str(events),
        }
    )
    args = ["-m", "tests.transport._server", "--transport", transport_name]
    process: asyncio.subprocess.Process | None = None
    with logs.open("w", encoding="utf-8") as output:
        transport: StdioTransport | StreamableHttpTransport
        if transport_name == "stdio":
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
            async with Client(transport, timeout=5, init_timeout=15, mode=mode) as client:
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


@pytest.mark.parametrize(
    "connected",
    [("stdio", "legacy"), ("streamable-http", "legacy")],
    ids=["stdio-legacy", "streamable-http-legacy"],
    indirect=True,
)
async def test_legacy_handshake_round_trip(connected: Connection) -> None:
    """Clients on a handshake-era protocol keep the read-only surface and an empty trace context.

    From mcp 2.3.0, such clients omit empty ``_meta`` and ``params`` on the wire.
    """
    client, _ = connected
    assert client.initialize_result is not None  # only the legacy initialize handshake sets it
    await client.ping()
    tools = {tool.name for tool in await client.list_tools()}
    assert "get_schema" in tools
    assert "node_delete" not in tools
    result = await client.call_tool("get_schema", {})
    assert json.loads(result.content[0].text) == {"TestWidget": "Widget"}  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    untraced = await client.call_tool("get_schema", {"branch": "trace-clean"})
    catalog = json.loads(untraced.content[0].text)  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    assert json.loads(catalog["TestWidget"]) == {"trace_id": "0" * 32, "span_id": "0" * 16, "tracestate": ""}


async def test_mounted_resource_template_matches_tool_result(connected: Connection) -> None:
    """Mounted templates retain their URI, MIME type and Unicode schema content."""
    client, _ = connected
    templates = await client.list_resource_templates()
    assert "infrahub://schema/{kind}" in {template.uri_template for template in templates}
    resource = await client.read_resource("infrahub://schema/TestWidget")
    result = await client.call_tool("get_schema", {"kind": "TestWidget"})
    assert str(resource[0].uri) == "infrahub://schema/TestWidget"
    assert resource[0].mime_type == "text/plain"
    detail = toon.decode(resource[0].text)  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    assert detail == toon.decode(result.data)
    assert detail["label"] == "Widget — 東京"
    assert detail["filters"] == [{"filter": "name__value", "type": "String"}]


async def test_resource_error_preserves_session(connected: Connection) -> None:
    """A missing mounted resource returns actionable guidance without closing the session."""
    client, _ = connected
    with pytest.raises(MCPError, match="Schema not found for kind 'MissingWidget'"):
        await client.read_resource("infrahub://schema/MissingWidget")
    resource = await client.read_resource("infrahub://schema")
    assert json.loads(resource[0].text) == {"TestWidget": "Widget"}  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize("tool_name", ["node_delete", "reset_session_branch"])
async def test_read_only_denies_direct_write_calls(connected: Connection, tool_name: str) -> None:
    """Hidden write tools cannot be invoked by bypassing discovery."""
    client, _ = connected
    assert tool_name not in {tool.name for tool in await client.list_tools()}
    with pytest.raises(MCPError, match="read-only mode"):
        await client.call_tool(tool_name, {})
    session = await client.call_tool("get_session_info", {})
    assert session.data["has_session_branch"] is False


async def test_invalid_tool_arguments_preserve_session(connected: Connection) -> None:
    """FastMCP rejects an invalid argument before the mounted tool reaches the SDK."""
    client, events = connected
    with pytest.raises(MCPError, match="Input should be a valid string"):
        await client.call_tool("query_graphql", {"query": 42})
    assert "graphql-executed" not in (await AsyncPath(events).read_text(encoding="utf-8")).splitlines()
    assert not (await client.call_tool("get_schema", {})).is_error


async def test_tool_error_does_not_execute_mutation(connected: Connection) -> None:
    """Application errors retain their message and never reach the SDK as mutations."""
    client, events = connected
    with pytest.raises(MCPError, match="Mutations are not allowed"):
        await client.call_tool("query_graphql", {"query": 'mutation { TestWidgetDelete(id: "example") { ok } }'})
    assert "graphql-executed" not in (await AsyncPath(events).read_text(encoding="utf-8")).splitlines()


async def test_empty_structured_tool_result_is_preserved(connected: Connection) -> None:
    """Empty GraphQL results remain dictionaries when FastMCP hydrates structured content."""
    client, events = connected
    result = await client.call_tool("query_graphql", {"query": "query { TestWidget { count } }"})
    assert not result.is_error
    assert result.structured_content == {}
    assert result.data == {}
    assert "graphql-executed" in (await AsyncPath(events).read_text(encoding="utf-8")).splitlines()


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


@pytest.mark.parametrize(
    ("tracestate", "expected_state"),
    [
        pytest.param("vendor=opaque", "vendor=opaque", id="valid"),
        pytest.param("invalid state", "", id="malformed"),
        pytest.param(",".join(f"vendor{index}=" + "x" * 256 for index in range(32)), "", id="oversized"),
    ],
)
async def test_trace_context_reaches_sdk_and_is_cleared(
    connected: Connection, tracestate: str, expected_state: str
) -> None:
    """The real API propagates valid parent IDs and safely rejects bad trace state."""
    client, _ = connected
    trace_id = "1234567890abcdef1234567890abcdef"
    span_id = "1234567890abcdef"
    result = await client.call_tool(
        "get_schema",
        {"branch": "trace-parent"},
        meta={"traceparent": f"00-{trace_id}-{span_id}-01", "tracestate": tracestate},
    )
    catalog = json.loads(result.content[0].text)  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    assert json.loads(catalog["TestWidget"]) == {
        "trace_id": trace_id,
        "span_id": span_id,
        "tracestate": expected_state,
    }

    untraced = await client.call_tool("get_schema", {"branch": "trace-clean"})
    catalog = json.loads(untraced.content[0].text)  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    assert json.loads(catalog["TestWidget"]) == {
        "trace_id": "0" * 32,
        "span_id": "0" * 16,
        "tracestate": "",
    }


async def test_concurrent_trace_contexts_stay_separate(connected: Connection) -> None:
    """Overlapping protocol requests retain their own OpenTelemetry context."""
    client, _ = connected
    trace_ids = [f"{index:032x}" for index in range(1, 5)]
    results = await asyncio.gather(
        *(
            client.call_tool(
                "get_schema",
                {"branch": f"trace-{trace_id}"},
                meta={"traceparent": f"00-{trace_id}-1234567890abcdef-01", "tracestate": f"vendor={trace_id}"},
            )
            for trace_id in trace_ids
        )
    )
    contexts = [json.loads(json.loads(result.content[0].text)["TestWidget"]) for result in results]  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]
    assert contexts == [
        {"trace_id": trace_id, "span_id": "1234567890abcdef", "tracestate": f"vendor={trace_id}"}
        for trace_id in trace_ids
    ]
