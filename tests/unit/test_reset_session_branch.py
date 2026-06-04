"""Tests for the reset/switch session-branch capability and the read-only write recovery net.

Covers ``reset_or_switch_session_branch`` (backing the ``reset_session_branch`` tool):
no-arg reset, switch to an existing branch, create-on-conformant, error-on-nonconformant,
default-branch rejection, merged-target rejection, and per-session isolation. Also covers
``_maybe_recover_read_only`` (FR-011): a write that fails because the branch was merged
mid-write clears the session entry and raises a retryable error.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError
from infrahub_sdk.branch import BranchStatus
from infrahub_sdk.exceptions import BranchNotFoundError, GraphQLError

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.tools.write import _assert_no_privileged_mutations, _maybe_recover_read_only
from infrahub_mcp.utils import AppContext, reset_or_switch_session_branch

_PATTERN = "mcp/session-{date}-{hex}"


def _make_ctx(app_ctx: AppContext) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    ctx.info = AsyncMock()
    ctx.warning = AsyncMock()
    ctx.debug = AsyncMock()
    ctx.error = AsyncMock()
    return ctx


def _app_ctx(**kwargs: object) -> AppContext:
    config = ServerConfig(auth_mode="none", branch_pattern=_PATTERN)
    return AppContext(client=MagicMock(), config=config, default_branch="main", **kwargs)  # type: ignore[arg-type]


class TestResetSessionBranch:
    async def test_reset_no_arg_clears_entry(self) -> None:
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[ctx.request_context.session] = "mcp/session-x"  # noqa: SLF001

        result = await reset_or_switch_session_branch(ctx, None)

        assert result["action"] == "reset"
        assert result["session_branch"] is None
        assert result["previous_branch"] == "mcp/session-x"
        assert ctx.request_context.session not in app_ctx._session_branches  # noqa: SLF001

    async def test_reset_no_arg_safe_when_empty(self) -> None:
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)

        result = await reset_or_switch_session_branch(ctx, None)

        assert result["action"] == "reset"
        assert result["previous_branch"] is None

    async def test_switch_to_existing_writable(self) -> None:
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)
        client = MagicMock()
        existing = MagicMock()
        existing.status = BranchStatus.OPEN
        existing.is_default = False
        client.branch.get = AsyncMock(return_value=existing)
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await reset_or_switch_session_branch(ctx, "mcp/session-existing")

        assert result["action"] == "switched"
        assert result["created"] is False
        assert result["session_branch"] == "mcp/session-existing"
        assert app_ctx._session_branches[ctx.request_context.session] == "mcp/session-existing"  # noqa: SLF001
        client.branch.create.assert_not_called()

    async def test_create_on_conformant_missing(self) -> None:
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)
        client = MagicMock()
        client.branch.get = AsyncMock(side_effect=BranchNotFoundError(identifier="x"))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await reset_or_switch_session_branch(ctx, "mcp/session-20260101-deadbeef")

        assert result["action"] == "created"
        assert result["created"] is True
        assert result["session_branch"] == "mcp/session-20260101-deadbeef"
        client.branch.create.assert_called_once()

    async def test_error_on_nonconformant_missing(self) -> None:
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)
        client = MagicMock()
        client.branch.get = AsyncMock(side_effect=BranchNotFoundError(identifier="x"))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client), pytest.raises(ToolError, match="omit"):
            await reset_or_switch_session_branch(ctx, "totally-random-name")

        client.branch.create.assert_not_called()

    async def test_reject_default_branch(self) -> None:
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)
        client = MagicMock()

        with (
            patch("infrahub_mcp.utils.get_client", return_value=client),
            pytest.raises(ToolError, match="propose_changes"),
        ):
            await reset_or_switch_session_branch(ctx, "main")

    async def test_reject_merged_target(self) -> None:
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)
        client = MagicMock()
        merged = MagicMock()
        merged.status = BranchStatus.MERGED
        merged.is_default = False
        client.branch.get = AsyncMock(return_value=merged)

        with patch("infrahub_mcp.utils.get_client", return_value=client), pytest.raises(ToolError):
            await reset_or_switch_session_branch(ctx, "mcp/session-merged")

    async def test_reject_branch_resolving_to_default(self) -> None:
        """A target whose resolved branch is is_default is rejected even if the name differs."""
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)
        client = MagicMock()
        resolved_default = MagicMock()
        resolved_default.status = BranchStatus.OPEN
        resolved_default.is_default = True
        client.branch.get = AsyncMock(return_value=resolved_default)

        with patch("infrahub_mcp.utils.get_client", return_value=client), pytest.raises(ToolError):
            await reset_or_switch_session_branch(ctx, "mcp/session-aliasmain")

    async def test_switch_isolated_per_session(self) -> None:
        app_ctx = _app_ctx()
        ctx_a = _make_ctx(app_ctx)
        ctx_b = _make_ctx(app_ctx)
        app_ctx._session_branches[ctx_b.request_context.session] = "mcp/session-B"  # noqa: SLF001

        result = await reset_or_switch_session_branch(ctx_a, None)

        assert result["action"] == "reset"
        assert app_ctx._session_branches[ctx_b.request_context.session] == "mcp/session-B"  # noqa: SLF001


class TestReadOnlyWriteRecovery:
    @staticmethod
    def _client(*, status: BranchStatus) -> MagicMock:
        client = MagicMock()
        branch = MagicMock()
        branch.status = status
        branch.is_default = False
        client.branch.get = AsyncMock(return_value=branch)
        return client

    async def test_merged_branch_confirmed_then_cleared_and_raises(self) -> None:
        """Read-only error + Infrahub confirms MERGED → clear the branch and raise retryable."""
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[ctx.request_context.session] = "mcp/session-merged"  # noqa: SLF001
        client = self._client(status=BranchStatus.MERGED)
        exc = GraphQLError(errors=[{"message": "Branch 'mcp/session-merged' has been merged and is read-only"}])

        with patch("infrahub_mcp.utils.get_client", return_value=client), pytest.raises(ToolError, match="Retry"):
            await _maybe_recover_read_only(ctx, exc)

        assert ctx.request_context.session not in app_ctx._session_branches  # noqa: SLF001

    async def test_read_only_attribute_error_does_not_clear(self) -> None:
        """FR-011 false-positive guard: 'read-only' attribute error on a writable branch must NOT clear it."""
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[ctx.request_context.session] = "mcp/session-ok"  # noqa: SLF001
        client = self._client(status=BranchStatus.OPEN)  # branch is actually fine
        exc = GraphQLError(errors=[{"message": "Attribute 'name' is read-only and cannot be updated"}])

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            await _maybe_recover_read_only(ctx, exc)  # must NOT raise

        assert app_ctx._session_branches[ctx.request_context.session] == "mcp/session-ok"  # noqa: SLF001

    async def test_non_read_only_error_is_noop(self) -> None:
        app_ctx = _app_ctx()
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[ctx.request_context.session] = "mcp/session-ok"  # noqa: SLF001
        client = MagicMock()
        client.branch.get = AsyncMock()
        exc = GraphQLError(errors=[{"message": "some unrelated validation failure"}])

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            await _maybe_recover_read_only(ctx, exc)  # returns without raising

        assert app_ctx._session_branches[ctx.request_context.session] == "mcp/session-ok"  # noqa: SLF001
        client.branch.get.assert_not_called()  # cheap pre-filter short-circuits, no round-trip


class TestPrivilegedMutationGuard:
    @pytest.mark.parametrize(
        "query",
        [
            'mutation { BranchMerge(data: {name: "x"}) { ok } }',
            'mutation { BranchRebase(data: {name: "x"}) { ok } }',
            'mutation { BranchDelete(data: {name: "x"}) { ok } }',
            'mutation { BranchCreate(data: {name: "x"}) { ok } }',
            "mutation { SchemaDropdownAdd(data: {}) { ok } }",
            "mutation { SchemaEnumRemove(data: {}) { ok } }",
        ],
    )
    def test_blocks_privileged_mutations(self, query: str) -> None:
        # Error must point the agent at the supported path (recovery guidance).
        with pytest.raises(ToolError, match="reset_session_branch"):
            _assert_no_privileged_mutations(query)

    def test_blocks_privileged_mutation_in_inline_fragment(self) -> None:
        # Must not be smuggled past the guard via a root inline fragment.
        with pytest.raises(ToolError):
            _assert_no_privileged_mutations('mutation { ... on Mutation { BranchMerge(data: {name: "x"}) { ok } } }')

    def test_blocks_privileged_mutation_in_fragment_spread(self) -> None:
        with pytest.raises(ToolError):
            _assert_no_privileged_mutations(
                'mutation { ...Evil } fragment Evil on Mutation { BranchMerge(data: {name: "x"}) { ok } }'
            )

    def test_rejects_non_mutation_operation(self) -> None:
        # mutate_graphql must reject reads (and subscriptions) — use query_graphql instead.
        with pytest.raises(ToolError, match="query_graphql"):
            _assert_no_privileged_mutations("query { CoreTag { edges { node { id } } } }")

    def test_allows_normal_node_mutation(self) -> None:
        # A regular data mutation must pass through untouched.
        _assert_no_privileged_mutations('mutation { CoreTagCreate(data: {name: {value: "web"}}) { ok } }')

    def test_rejects_invalid_syntax(self) -> None:
        with pytest.raises(ToolError, match="retry"):
            _assert_no_privileged_mutations("mutation { broken(")
