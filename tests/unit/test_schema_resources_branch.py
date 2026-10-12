"""Branch-aware schema resources (spec FR-010, SC-004)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import Client
from infrahub_sdk.exceptions import BranchNotFoundError
from mcp import MCPError

import infrahub_mcp.resources.schema as resources_module
import infrahub_mcp.tools.schema as tools_module
from infrahub_mcp.config import ServerConfig

if TYPE_CHECKING:
    from collections.abc import Iterator

KNOWN_BRANCHES = {None, "b1"}
calls: list[tuple[str, str | None, str | None]] = []


async def _fake_catalog(client: Any, branch: str | None = None) -> dict[str, str]:  # noqa: RUF029
    calls.append(("catalog", None, branch))
    if branch not in KNOWN_BRANCHES:
        raise BranchNotFoundError(identifier=str(branch))
    return {"LocationSite": f"Site on {branch or 'default'}"}


async def _fake_detail(  # noqa: RUF029
    client: Any,
    kind: str,
    branch: str | None = None,
    expand_peers: bool = True,
) -> dict[str, Any]:
    calls.append(("detail", kind, branch))
    if branch not in KNOWN_BRANCHES:
        raise BranchNotFoundError(identifier=str(branch))
    return {"kind": kind, "branch": branch or "default", "expand_peers": expand_peers, "attributes": [{"name": "name"}]}


@pytest.fixture(autouse=True)
def _fake_schema_helpers() -> Iterator[None]:
    calls.clear()
    config = ServerConfig()
    with (
        patch.object(resources_module, "get_schema_catalog", _fake_catalog),
        patch.object(resources_module, "get_schema_detail", _fake_detail),
        patch.object(resources_module, "get_client", return_value=MagicMock()),
        patch.object(resources_module, "get_config", return_value=config),
        patch.object(tools_module, "get_schema_catalog", _fake_catalog),
        patch.object(tools_module, "get_schema_detail", _fake_detail),
        patch.object(tools_module, "get_client", return_value=MagicMock()),
        patch.object(tools_module, "get_config", return_value=config),
    ):
        yield


async def _read(uri: str) -> str:
    async with Client(resources_module.mcp) as client:
        contents = await client.read_resource(uri)
    return contents[0].text  # type: ignore[union-attr]


async def _get_schema(arguments: dict[str, str]) -> str:
    async with Client(tools_module.mcp) as client:
        result = await client.call_tool("get_schema", arguments)
    return result.content[0].text  # type: ignore[union-attr]


async def test_static_catalog_is_still_listed() -> None:
    async with Client(resources_module.mcp) as client:
        uris = {str(resource.uri) for resource in await client.list_resources()}
    assert "infrahub://schema" in uris


@pytest.mark.parametrize(
    ("uri", "expected_call"),
    [
        ("infrahub://schema", ("catalog", None, None)),
        ("infrahub://schema?branch=b1", ("catalog", None, "b1")),
        ("infrahub://schema/LocationSite", ("detail", "LocationSite", None)),
        ("infrahub://schema/LocationSite?branch=b1", ("detail", "LocationSite", "b1")),
    ],
)
async def test_resources_pass_the_branch(uri: str, expected_call: tuple[str, str | None, str | None]) -> None:
    await _read(uri)
    assert calls == [expected_call]


@pytest.mark.parametrize(
    ("uri", "arguments"),
    [
        ("infrahub://schema", {}),
        ("infrahub://schema?branch=b1", {"branch": "b1"}),
        ("infrahub://schema/LocationSite", {"kind": "LocationSite"}),
        ("infrahub://schema/LocationSite?branch=b1", {"kind": "LocationSite", "branch": "b1"}),
    ],
)
async def test_resource_matches_get_schema(uri: str, arguments: dict[str, str]) -> None:
    """SC-004: for the same kind and branch, the resource and get_schema return the same text."""
    assert await _read(uri) == await _get_schema(arguments)


@pytest.mark.parametrize("uri", ["infrahub://schema?branch=missing", "infrahub://schema/LocationSite?branch=missing"])
async def test_unknown_branch_names_get_schema(uri: str) -> None:
    with pytest.raises(MCPError, match=r"get_schema\(\)"):
        async with Client(resources_module.mcp) as client:
            await client.read_resource(uri)
