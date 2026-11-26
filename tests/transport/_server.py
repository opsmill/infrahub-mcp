"""Launch the production CLI with a deterministic Infrahub SDK test double."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from infrahub_sdk.exceptions import SchemaNotFoundError
from opentelemetry import trace

from infrahub_mcp import _cli


def _record(event: str) -> None:
    with Path(os.environ["MCP_TEST_EVENTS"]).open("a", encoding="utf-8") as stream:
        stream.write(f"{event}\n")


_DEFAULT_BRANCH = "main"
_DEFAULT_LABEL = "Widget — 東京"


def _widget(label: str) -> SimpleNamespace:
    return SimpleNamespace(
        kind="TestWidget",
        namespace="Test",
        label=label,
        attributes=[SimpleNamespace(name="name", kind="Text", optional=False)],
        relationships=[],
    )


class _Response:
    def __init__(self, *, payload: dict[str, object] | None = None, text: str = "") -> None:
        self.status_code = 200
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _Schema:
    """Model the SDK schema surface the server reads, including the internals the schema cache uses."""

    def __init__(self) -> None:
        self.cache: dict[str, SimpleNamespace] = {}

    def set_cache(self, schema: SimpleNamespace, branch: str) -> None:
        self.cache[branch] = schema

    async def get(self, kind: str, branch: str | None = None) -> SimpleNamespace:
        nodes = await self.all(branch=branch)
        if kind not in nodes:
            raise SchemaNotFoundError(kind)
        return nodes[kind]

    async def _fetch(self, branch: str) -> SimpleNamespace:
        return SimpleNamespace(hash=f"hash-{branch}", nodes=await self.all(branch=branch))

    async def all(self, branch: str | None = None) -> dict[str, SimpleNamespace]:
        if branch == "slow":
            _record("slow-started")
            try:
                await asyncio.Event().wait()
            finally:
                _record("slow-cleaned")
        # Yield so simultaneous requests can overlap at the SDK boundary.
        await asyncio.sleep(0)
        label = _DEFAULT_LABEL if branch in {None, _DEFAULT_BRANCH} else branch
        if branch and branch.startswith("trace-"):
            span_context = trace.get_current_span().get_span_context()
            label = json.dumps(
                {
                    "trace_id": format(span_context.trace_id, "032x"),
                    "span_id": format(span_context.span_id, "016x"),
                    "tracestate": span_context.trace_state.to_header(),
                }
            )
        return {"TestWidget": _widget(label)}


class _Branches:
    async def all(self) -> dict[str, SimpleNamespace]:
        return {_DEFAULT_BRANCH: SimpleNamespace(name=_DEFAULT_BRANCH, is_default=True)}


class _SDK:
    address = "http://infrahub.test"

    def __init__(self) -> None:
        self.schema = _Schema()
        self.branch = _Branches()

    async def _get(self, url: str) -> _Response:
        """Answer the schema cache's ``/api/schema/summary`` and ``/schema.graphql`` reads."""
        await asyncio.sleep(0)
        parsed = urlsplit(url)
        branch = parse_qs(parsed.query).get("branch", [_DEFAULT_BRANCH])[0]
        if parsed.path == "/api/schema/summary":
            return _Response(payload={"main": f"hash-{branch}"})
        return _Response(text="type Query { TestWidget: String }")

    async def get_version(self) -> str:
        return "test-version"

    async def execute_graphql(self, query: str, branch_name: str | None = None) -> dict[str, object]:
        _record("graphql-executed")
        await asyncio.sleep(0)
        return {}


def main() -> None:
    """Keep CLI, lifespan, middleware and transport real; replace only the SDK."""
    _record(f"pid:{os.getpid()}")
    try:
        with patch("infrahub_mcp.server.InfrahubClient", return_value=_SDK()):
            _cli.main()
    except KeyboardInterrupt:
        # Uvicorn re-raises SIGINT after completing its graceful shutdown.
        pass
    _record("server-exited")


if __name__ == "__main__":
    main()
