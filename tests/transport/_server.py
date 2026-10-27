"""Launch the production CLI with a deterministic Infrahub SDK test double."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from infrahub_sdk.exceptions import SchemaNotFoundError

from infrahub_mcp import _cli


def _record(event: str) -> None:
    with Path(os.environ["MCP_TEST_EVENTS"]).open("a", encoding="utf-8") as stream:
        stream.write(f"{event}\n")


class _Schema:
    async def get(self, kind: str, branch: str | None = None) -> SimpleNamespace:
        await asyncio.sleep(0)
        if kind != "TestWidget":
            raise SchemaNotFoundError(kind)
        return SimpleNamespace(
            kind=kind,
            namespace="Test",
            label="Widget — 東京",
            attributes=[SimpleNamespace(name="name", kind="Text", optional=False)],
            relationships=[],
        )

    async def all(self, branch: str | None = None) -> dict[str, SimpleNamespace]:
        if branch == "slow":
            _record("slow-started")
            try:
                await asyncio.Event().wait()
            finally:
                _record("slow-cleaned")
        # Yield so simultaneous requests can overlap at the SDK boundary.
        await asyncio.sleep(0)
        return {"TestWidget": SimpleNamespace(namespace="Test", label=branch or "Widget")}


class _SDK:
    def __init__(self) -> None:
        self.schema = _Schema()

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
