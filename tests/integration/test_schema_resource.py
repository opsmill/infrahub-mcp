"""Integration: the `infrahub://schema` resource reflects the seeded schema (contract R1, FR-005)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.integration._util import resource_json

if TYPE_CHECKING:
    from fastmcp import Client

pytestmark = [pytest.mark.integration]


async def test_schema_resource_lists_seeded_kind(
    mcp_client: Client,
    seeded_infrahub: dict[str, object],
) -> None:
    contents = await mcp_client.read_resource("infrahub://schema")
    catalog = resource_json(contents)  # {kind_name: human_label}

    assert seeded_infrahub["widget_kind"] in catalog
