#!/usr/bin/env python3
"""Integration test script for Infrahub MCP server against a live instance.

Usage:
    export INFRAHUB_ADDRESS=https://sandbox.infrahub.app
    export INFRAHUB_API_TOKEN=<your-token>
    uv run python scripts/test_sandbox.py

Runs a sequence of MCP tool calls via FastMCP's in-process Client and
reports timing + approximate token usage for each operation.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from fastmcp import Client


def token_estimate(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English/structured data."""
    return len(text) // 4


def print_result(label: str, elapsed: float, result: Any, *, show_data: bool = True) -> dict[str, Any]:
    """Print and return a timing record."""
    text = str(result)
    tokens = token_estimate(text)
    status = "OK" if result else "EMPTY"
    print(f"  {label:.<45} {elapsed:.3f}s  ~{tokens:>5} tokens  [{status}]")
    if show_data and len(text) < 500:
        print(f"    {text[:500]}")
    return {"label": label, "elapsed_s": elapsed, "est_tokens": tokens}


async def run_tests() -> None:
    from infrahub_mcp.server import mcp as server

    records: list[dict[str, Any]] = []
    print("\n=== Infrahub MCP Sandbox Integration Test ===\n")

    async with Client(server) as client:
        # 1. Health check (via tool listing as proxy — real /health needs HTTP)
        t0 = time.monotonic()
        tools = await client.list_tools()
        elapsed = time.monotonic() - t0
        tool_names = [t.name for t in tools]
        records.append(print_result("list_tools", elapsed, tool_names))

        # 2. Schema catalog resource
        t0 = time.monotonic()
        schema_res = await client.read_resource("infrahub://schema")
        elapsed = time.monotonic() - t0
        schema_text = schema_res[0].text if schema_res else ""  # type: ignore[attr-defined]
        schema_data = json.loads(schema_text) if schema_text else {}
        records.append(print_result("resource:schema", elapsed, f"{len(schema_data)} kinds"))

        # Pick a kind to test with
        test_kind = None
        for kind_name in schema_data:
            if "Device" in kind_name or "Interface" in kind_name:
                test_kind = kind_name
                break
        if not test_kind and schema_data:
            test_kind = next(iter(schema_data))
        print(f"\n  Using test kind: {test_kind}\n")

        # 3. Schema detail resource
        if test_kind:
            t0 = time.monotonic()
            detail_res = await client.read_resource(f"infrahub://schema/{test_kind}")
            elapsed = time.monotonic() - t0
            detail_text = detail_res[0].text if detail_res else ""  # type: ignore[attr-defined]
            records.append(print_result(f"resource:schema/{test_kind}", elapsed, detail_text, show_data=False))
            print(f"    (TOON payload: {len(detail_text)} chars)")

        # 4. get_schema tool
        t0 = time.monotonic()
        schema_tool = await client.call_tool("get_schema", {})
        elapsed = time.monotonic() - t0
        records.append(print_result("tool:get_schema()", elapsed, schema_tool, show_data=False))

        # 5. get_schema with kind
        if test_kind:
            t0 = time.monotonic()
            schema_kind = await client.call_tool("get_schema", {"kind": test_kind})
            elapsed = time.monotonic() - t0
            records.append(print_result(f"tool:get_schema({test_kind})", elapsed, schema_kind, show_data=False))

        # 6. get_nodes
        if test_kind:
            t0 = time.monotonic()
            nodes = await client.call_tool("get_nodes", {"kind": test_kind, "limit": 5})
            elapsed = time.monotonic() - t0
            records.append(print_result(f"tool:get_nodes({test_kind}, limit=5)", elapsed, nodes, show_data=False))

        # 7. get_nodes with include_attributes
        if test_kind:
            t0 = time.monotonic()
            nodes_full = await client.call_tool(
                "get_nodes", {"kind": test_kind, "limit": 3, "include_attributes": True}
            )
            elapsed = time.monotonic() - t0
            records.append(
                print_result(f"tool:get_nodes({test_kind}, attrs, limit=3)", elapsed, nodes_full, show_data=False)
            )

        # 8. query_graphql
        t0 = time.monotonic()
        gql_result = await client.call_tool(
            "query_graphql", {"query": "query { InfrahubInfo { version } }"}
        )
        elapsed = time.monotonic() - t0
        records.append(print_result("tool:query_graphql(version)", elapsed, gql_result))

        # 9. Branches resource
        t0 = time.monotonic()
        branches_res = await client.read_resource("infrahub://branches")
        elapsed = time.monotonic() - t0
        branches_text = branches_res[0].text if branches_res else ""  # type: ignore[attr-defined]
        records.append(print_result("resource:branches", elapsed, branches_text, show_data=False))

        # 10. GraphQL schema resource (large)
        t0 = time.monotonic()
        sdl_res = await client.read_resource("infrahub://graphql-schema")
        elapsed = time.monotonic() - t0
        sdl_text = sdl_res[0].text if sdl_res else ""  # type: ignore[attr-defined]
        records.append(print_result("resource:graphql-schema", elapsed, f"{len(sdl_text)} chars SDL"))

    # Summary
    print("\n=== Summary ===\n")
    total_time = sum(r["elapsed_s"] for r in records)
    total_tokens = sum(r["est_tokens"] for r in records)
    print(f"  Total time:    {total_time:.3f}s")
    print(f"  Total tokens:  ~{total_tokens}")
    print(f"  Operations:    {len(records)}")
    print(f"  Avg latency:   {total_time / len(records):.3f}s")
    print()


if __name__ == "__main__":
    try:
        asyncio.run(run_tests())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nFATAL: {e}", file=sys.stderr)
        sys.exit(1)
