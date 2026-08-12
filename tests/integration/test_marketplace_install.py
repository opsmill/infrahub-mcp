"""Integration: marketplace install lands on the session branch, never on main (US2, SC-002).

The marketplace is an external service, so the fetch is mocked; the *install* half
(SDK ``schema.load`` onto the session branch) runs against the real testcontainers
Infrahub. Verifies FR-005 (install via SDK), branch isolation (Constitution III), and
FR-006 (read-only blocks install).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp.exceptions import ToolError
from infrahub_sdk.exceptions import SchemaNotFoundError
from mcp import McpError

from infrahub_mcp.marketplace import MarketplaceClient, SchemaPayload

if TYPE_CHECKING:
    from fastmcp import Client
    from infrahub_sdk import InfrahubClient

pytestmark = [pytest.mark.integration]

# A minimal, valid schema distinct from the seeded TestingWidget — resolves to "TestingGadget".
_GADGET_KIND = "TestingGadget"
_GADGET_YAML = """\
version: "1.0"
nodes:
  - name: Gadget
    namespace: Testing
    label: Gadget
    default_filter: name__value
    display_labels:
      - name__value
    human_friendly_id:
      - name__value
    attributes:
      - name: name
        kind: Text
        unique: true
"""


async def test_install_lands_on_session_branch_not_main(
    mcp_client: Client,
    infrahub_client: InfrahubClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Must stay async: it replaces the async MarketplaceClient.get_schema.
    async def fake_get_schema(  # noqa: RUF029
        self: MarketplaceClient, ref: str, version: str | None = None
    ) -> SchemaPayload:
        return SchemaPayload(
            namespace="opsmill", name="gadget", resolved_version="1.0.0", yaml=_GADGET_YAML, metadata=None
        )

    monkeypatch.setattr(MarketplaceClient, "get_schema", fake_get_schema)

    result = await mcp_client.call_tool("marketplace_install", {"ref": "opsmill/gadget"})
    assert not result.is_error
    data = result.data  # type: ignore[attr-defined]
    branch = data["branch"]

    # The Infrahub container is session-scoped, so the branch this tool created must be
    # torn down here — nothing else owns it, and it would accumulate across runs.
    try:
        assert branch != "main"
        assert data["installed"] == "opsmill/gadget"

        # The new kind exists on the session branch...
        on_branch = await infrahub_client.schema.get(kind=_GADGET_KIND, branch=branch)
        assert on_branch.kind == _GADGET_KIND

        # ...but NOT on main (branch-safe by default — Constitution III / SC-002).
        with pytest.raises(SchemaNotFoundError):
            await infrahub_client.schema.get(kind=_GADGET_KIND, branch="main")
    finally:
        await infrahub_client.branch.delete(branch_name=branch)


async def test_install_blocked_in_read_only(mcp_client_readonly: Client) -> None:
    # Install is write-tagged and unmounted in read-only mode: the call raises before
    # any marketplace request is made (FR-006).
    with pytest.raises((ToolError, McpError)):
        await mcp_client_readonly.call_tool("marketplace_install", {"ref": "opsmill/gadget"})
