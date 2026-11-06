"""Tests for per-session branch resolution, recovery, and name conformance.

The active session branch is tracked per caller (keyed by ``_session_key``:
authenticated caller and validated MCP session id, else the server process) on
``AppContext``. The cached branch is validated against Infrahub
before reuse; if it was deleted (``BranchNotFoundError``) or merged / is being
removed (``status`` MERGED/DELETING — still present but read-only), the cache is
cleared and a fresh branch is provisioned without a server restart.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastmcp.server.auth import AccessToken
from infrahub_sdk.branch import BranchStatus
from infrahub_sdk.exceptions import BranchNotFoundError

from infrahub_mcp.auth import get_caller_identity, reset_passthrough_token, set_passthrough_token
from infrahub_mcp.config import ServerConfig
from infrahub_mcp.utils import (
    _MAX_SESSION_ENTRIES,
    AppContext,
    _session_key,
    _session_lock,
    _set_session_branch,
    branch_name_conforms,
    get_or_create_session_branch,
    get_session_branch,
)


def _make_ctx(app_ctx: AppContext) -> MagicMock:
    """Create a mock FastMCP Context with its own transport-validated MCP session id."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    ctx.request_context.session._connection.session_id = uuid4().hex  # noqa: SLF001
    ctx.info = AsyncMock()
    ctx.warning = AsyncMock()
    ctx.debug = AsyncMock()
    ctx.error = AsyncMock()
    return ctx


def _branch(status: BranchStatus) -> MagicMock:
    branch = MagicMock()
    branch.status = status
    return branch


class TestGetOrCreateSessionBranch:
    async def test_returns_cached_branch_when_it_still_exists(self) -> None:
        """A still-writable cached branch is reused — no re-create."""
        config = ServerConfig(auth_mode="none")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[_session_key(ctx)] = "mcp/session-existing"  # noqa: SLF001

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=_branch(BranchStatus.OPEN))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result == "mcp/session-existing"
        assert get_session_branch(ctx) == "mcp/session-existing"
        client.branch.create.assert_not_called()
        client.branch.get.assert_called_once_with(branch_name="mcp/session-existing")

    @pytest.mark.parametrize("status", [BranchStatus.OPEN, BranchStatus.NEED_REBASE])
    async def test_reuses_writable_statuses(self, status: BranchStatus) -> None:
        """OPEN and NEED_REBASE branches are writable and reused."""
        config = ServerConfig(auth_mode="none")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[_session_key(ctx)] = "mcp/session-reuse"  # noqa: SLF001

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=_branch(status))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result == "mcp/session-reuse"
        client.branch.create.assert_not_called()

    async def test_recreates_when_cached_branch_was_deleted(self) -> None:
        """A deleted cached branch (BranchNotFoundError) triggers creation of a new one."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[_session_key(ctx)] = "mcp/session-stale"  # noqa: SLF001

        client = MagicMock()
        client.branch.get = AsyncMock(side_effect=BranchNotFoundError(identifier="mcp/session-stale"))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result != "mcp/session-stale"
        assert result.startswith("mcp/session-")
        assert get_session_branch(ctx) == result
        client.branch.create.assert_called_once()
        ctx.warning.assert_awaited()

    @pytest.mark.parametrize("status", [BranchStatus.MERGED, BranchStatus.DELETING])
    async def test_recovers_when_cached_branch_unwritable(self, status: BranchStatus) -> None:
        """A merged/deleting cached branch (present but read-only) is recovered onto a new branch."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[_session_key(ctx)] = "mcp/session-merged"  # noqa: SLF001

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=_branch(status))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result != "mcp/session-merged"
        assert result.startswith("mcp/session-")
        assert get_session_branch(ctx) == result
        client.branch.create.assert_called_once()
        ctx.warning.assert_awaited()  # SC-005: old + new named

    async def test_creates_when_no_cached_branch(self) -> None:
        """First write of a session creates a new branch — no validation lookup."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)

        client = MagicMock()
        client.branch.get = AsyncMock()
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result.startswith("mcp/session-")
        assert get_session_branch(ctx) == result
        client.branch.create.assert_called_once()
        client.branch.get.assert_not_called()

    async def test_recovery_isolated_per_session(self) -> None:
        """Recovery in one session does not touch another session's branch (FR-010 / SC-006)."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx_a = _make_ctx(app_ctx)
        ctx_b = _make_ctx(app_ctx)
        app_ctx._session_branches[_session_key(ctx_a)] = "mcp/session-A"  # noqa: SLF001
        app_ctx._session_branches[_session_key(ctx_b)] = "mcp/session-B"  # noqa: SLF001

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=_branch(BranchStatus.MERGED))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            await get_or_create_session_branch(ctx_a)

        # Session B is untouched by Session A's recovery.
        assert get_session_branch(ctx_b) == "mcp/session-B"
        assert get_session_branch(ctx_a) != "mcp/session-A"

    async def test_concurrent_first_writes_converge_on_one_branch(self) -> None:
        """Concurrent writes in one session create exactly one branch (FR-008)."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=_branch(BranchStatus.OPEN))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            first, second = await asyncio.gather(
                get_or_create_session_branch(ctx),
                get_or_create_session_branch(ctx),
            )

        assert first == second
        client.branch.create.assert_called_once()


def _make_sessionless_ctx(app_ctx: AppContext) -> MagicMock:
    """Create a mock Context as the 2026-07-28 protocol sends it: no MCP session id."""
    ctx = _make_ctx(app_ctx)
    ctx.request_context.session._connection.session_id = None  # noqa: SLF001
    ctx.request_context.request.headers = {}
    return ctx


class TestSessionKey:
    def test_uses_validated_session_id_when_present(self) -> None:
        app_ctx = AppContext(client=MagicMock(), config=ServerConfig(auth_mode="none"))
        ctx = _make_ctx(app_ctx)
        ctx.request_context.session._connection.session_id = "abc"  # noqa: SLF001

        assert _session_key(ctx) == "session:abc"

    def test_ignores_unvalidated_session_id_header(self) -> None:
        """A raw ``mcp-session-id`` header is not part of the key.

        On the 2026-07-28 protocol and in stateless mode the transport does not
        validate the header, so a client could send random ids to fill the shared
        map and evict other callers' branches.
        """
        app_ctx = AppContext(client=MagicMock(), config=ServerConfig(auth_mode="none"))
        ctx = _make_sessionless_ctx(app_ctx)
        ctx.request_context.request.headers = {"mcp-session-id": "attacker-chosen"}

        assert _session_key(ctx) == "process"

    def test_falls_back_to_process_key_without_session_or_credentials(self) -> None:
        app_ctx = AppContext(client=MagicMock(), config=ServerConfig(auth_mode="none"))

        assert _session_key(_make_sessionless_ctx(app_ctx)) == "process"

    def test_uses_hashed_caller_identity_without_session_id(self) -> None:
        app_ctx = AppContext(client=MagicMock(), config=ServerConfig(auth_mode="none"))
        reset_token = set_passthrough_token("secret-token-a")
        try:
            key_a = _session_key(_make_sessionless_ctx(app_ctx))
        finally:
            reset_passthrough_token(reset_token)
        reset_token = set_passthrough_token("secret-token-b")
        try:
            key_b = _session_key(_make_sessionless_ctx(app_ctx))
        finally:
            reset_passthrough_token(reset_token)

        assert key_a.startswith("caller:")
        assert key_a != key_b
        assert "secret-token" not in key_a

    def test_session_id_cannot_cross_callers(self) -> None:
        """Two callers sending the same session id get different keys."""
        app_ctx = AppContext(client=MagicMock(), config=ServerConfig(auth_mode="none"))
        keys = []
        for token in ("secret-token-a", "secret-token-b"):
            ctx = _make_ctx(app_ctx)
            ctx.request_context.session._connection.session_id = "shared"  # noqa: SLF001
            reset_token = set_passthrough_token(token)
            try:
                keys.append(_session_key(ctx))
            finally:
                reset_passthrough_token(reset_token)

        assert keys[0] != keys[1]
        assert all(key.endswith("|session:shared") for key in keys)

    async def test_branch_survives_new_session_object_per_call(self) -> None:
        """Regression: a new session object on every call must still find the branch.

        From protocol 2026-07-28 each request gets a new session object, so keying on
        it made ``propose_changes`` fail with "No session branch exists yet".
        """
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        client = MagicMock()
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            created = await get_or_create_session_branch(_make_sessionless_ctx(app_ctx))

        assert get_session_branch(_make_sessionless_ctx(app_ctx)) == created


def _access_token(value: str, claims: dict[str, str]) -> AccessToken:
    return AccessToken(token=value, client_id="app", scopes=[], claims=claims)


class TestCallerIdentity:
    @staticmethod
    def _identity(token: AccessToken) -> str | None:
        with patch("fastmcp.server.dependencies.get_access_token", return_value=token):
            return get_caller_identity()

    def test_oidc_identity_differs_per_subject(self) -> None:
        claims = {"iss": "https://idp.example"}
        user_a = _access_token("tok-a", {**claims, "sub": "alice"})
        user_b = _access_token("tok-b", {**claims, "sub": "bob"})

        assert self._identity(user_a) != self._identity(user_b)

    def test_oidc_identity_stable_across_tokens_of_one_subject(self) -> None:
        claims = {"iss": "https://idp.example", "sub": "alice"}
        first = _access_token("tok-1", claims)
        refreshed = _access_token("tok-2", claims)

        assert self._identity(first) == self._identity(refreshed)

    def test_oidc_tokens_without_subject_never_collide(self) -> None:
        """Without ``sub``, client id and issuer are the same for every user: use the token."""
        claims = {"iss": "https://idp.example"}
        user_a = _access_token("tok-a", claims)
        user_b = _access_token("tok-b", claims)

        identity_a = self._identity(user_a)
        assert identity_a is not None
        assert identity_a != self._identity(user_b)
        assert "tok-a" not in identity_a


class TestSessionStateLifecycle:
    def test_least_recently_used_entry_dropped_past_limit(self) -> None:
        """The branch map keeps at most ``_MAX_SESSION_ENTRIES`` keys (no unbounded growth)."""
        app_ctx = AppContext(client=MagicMock(), config=ServerConfig(auth_mode="none"))

        for index in range(_MAX_SESSION_ENTRIES + 1):
            _set_session_branch(app_ctx, f"session:{index}", f"mcp/session-{index}")

        assert len(app_ctx._session_branches) == _MAX_SESSION_ENTRIES  # noqa: SLF001
        assert "session:0" not in app_ctx._session_branches  # noqa: SLF001
        assert f"session:{_MAX_SESSION_ENTRIES}" in app_ctx._session_branches  # noqa: SLF001

    def test_reading_a_branch_keeps_its_key_from_eviction(self) -> None:
        """A key whose branch is read is the most recently used, so it is not dropped first."""
        app_ctx = AppContext(client=MagicMock(), config=ServerConfig(auth_mode="none"))
        ctx = _make_sessionless_ctx(app_ctx)
        _set_session_branch(app_ctx, _session_key(ctx), "mcp/session-active")
        for index in range(_MAX_SESSION_ENTRIES - 1):
            _set_session_branch(app_ctx, f"session:{index}", f"mcp/session-{index}")

        assert get_session_branch(ctx) == "mcp/session-active"
        _set_session_branch(app_ctx, "session:new", "mcp/session-new")

        assert get_session_branch(ctx) == "mcp/session-active"
        assert "session:0" not in app_ctx._session_branches  # noqa: SLF001

    async def test_lock_trim_skips_locks_in_use(self) -> None:
        """Past the limit, unused locks are dropped even when the oldest lock is in use."""
        app_ctx = AppContext(client=MagicMock(), config=ServerConfig(auth_mode="none"))
        locks = app_ctx._session_locks  # noqa: SLF001
        async with _session_lock(app_ctx, "busy"):
            for index in range(_MAX_SESSION_ENTRIES + 5):
                async with _session_lock(app_ctx, f"session:{index}"):
                    pass

            assert len(locks) == _MAX_SESSION_ENTRIES
            assert "busy" in locks
        assert app_ctx._session_lock_users == {}  # noqa: SLF001

    async def test_lock_with_waiters_is_not_dropped_after_release(self) -> None:
        """A lock whose waiter has not resumed yet stays in the map.

        ``asyncio.Lock.locked()`` is ``False`` between ``release()`` and the waiter
        resuming. Dropping the lock then would let a new task for the same key take
        a second lock and create a second branch.
        """
        app_ctx = AppContext(client=MagicMock(), config=ServerConfig(auth_mode="none"))
        locks = app_ctx._session_locks  # noqa: SLF001
        holder = AsyncExitStack()
        await holder.enter_async_context(_session_lock(app_ctx, "key"))

        async def waiter() -> None:
            async with _session_lock(app_ctx, "key"):
                pass

        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        # Fill the map so that "key" is the least recently used lock.
        for index in range(_MAX_SESSION_ENTRIES - 1):
            async with _session_lock(app_ctx, f"session:{index}"):
                pass
        assert next(iter(locks)) == "key"
        key_lock = locks["key"]

        await holder.aclose()
        # The holder released the lock; the waiter has not resumed yet.
        assert not key_lock.locked()
        assert not waiter_task.done()
        async with _session_lock(app_ctx, "other"):
            assert locks.get("key") is key_lock
        await waiter_task


class TestBranchNameConforms:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("mcp/session-20260604-ab12cd34", True),
            ("mcp/session-2026-ab12cd34", False),  # {date} wrong length
            ("mcp/session-20260604-ZZZZ", False),  # {hex} not 8 lowercase hex
            ("totally-random-name", False),  # no match
            ("mcp/session-20260604-ab12cd34/extra", False),  # trailing extra
        ],
    )
    def test_default_pattern(self, name: str, expected: bool) -> None:
        assert branch_name_conforms(name, "mcp/session-{date}-{hex}") is expected

    def test_fixed_pattern_requires_exact_match(self) -> None:
        assert branch_name_conforms("mybranch", "mybranch") is True
        assert branch_name_conforms("other", "mybranch") is False

    def test_user_placeholder_respects_separators(self) -> None:
        assert branch_name_conforms("mcp/alice/work", "mcp/{user}/work") is True
        assert branch_name_conforms("mcp/alice/nope", "mcp/{user}/work") is False
        # {user} must not span literal '/' separators (would otherwise over-match).
        assert branch_name_conforms("mcp/a/b/work", "mcp/{user}/work") is False

    def test_rejects_disallowed_characters(self) -> None:
        assert branch_name_conforms("mcp/session-20260604-ab12cd34 ", "mcp/session-{date}-{hex}") is False
