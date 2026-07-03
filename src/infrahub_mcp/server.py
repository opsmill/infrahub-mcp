import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from infrahub_sdk.client import InfrahubClient
from infrahub_sdk.exceptions import AuthenticationError, ServerNotReachableError, ServerNotResponsiveError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from infrahub_mcp.auth import (
    create_auth_provider,
    reset_passthrough_basic,
    reset_passthrough_token,
    set_passthrough_basic,
    set_passthrough_token,
)
from infrahub_mcp.config import ServerConfig, load_config
from infrahub_mcp.constants import (
    AUTH_MODE_BASIC_PASSTHROUGH,
    AUTH_MODE_OIDC,
    AUTH_MODE_TOKEN_PASSTHROUGH,
)
from infrahub_mcp.middleware import (
    configure_middleware,
    get_caching_middleware,
    get_error_handling,
    get_metrics,
)
from infrahub_mcp.prompts.prompts import mcp as prompts_mcp
from infrahub_mcp.resources.branches import mcp as branches_resources_mcp
from infrahub_mcp.resources.schema import mcp as schema_resources_mcp
from infrahub_mcp.tools.gql import mcp as graphql_mcp
from infrahub_mcp.tools.nodes import mcp as nodes_mcp
from infrahub_mcp.tools.schema import mcp as schema_tools_mcp
from infrahub_mcp.tools.session import mcp as session_mcp
from infrahub_mcp.tools.traversal import mcp as traversal_mcp
from infrahub_mcp.tools.write import mcp as write_mcp
from infrahub_mcp.utils import AppContext

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    # ASGI 3.0 application callable type — avoids a runtime dependency on asgiref.
    ASGIApp = Callable[..., Awaitable[None]]

_config: ServerConfig = load_config()


def _validate_env() -> None:
    """Validate required environment variables at startup and raise with clear guidance."""
    # Passthrough modes: credentials come from the client, not env vars.
    if _config.auth_mode in {AUTH_MODE_TOKEN_PASSTHROUGH, AUTH_MODE_BASIC_PASSTHROUGH}:
        return

    address = os.environ.get("INFRAHUB_ADDRESS")
    if not address:
        msg = "INFRAHUB_ADDRESS is required. Set it to the URL of your Infrahub instance (e.g. http://localhost:8000)."
        raise RuntimeError(msg)

    api_token = os.environ.get("INFRAHUB_API_TOKEN")
    username = os.environ.get("INFRAHUB_USERNAME")
    password = os.environ.get("INFRAHUB_PASSWORD")

    if not api_token and not (username and password):
        msg = "Authentication required. Set INFRAHUB_API_TOKEN  —or—  both INFRAHUB_USERNAME and INFRAHUB_PASSWORD."
        raise RuntimeError(msg)


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:  # noqa: ARG001
    """Manage the application lifecycle: validate config, create client, yield context."""
    _validate_env()
    client = (
        None if _config.auth_mode in {AUTH_MODE_TOKEN_PASSTHROUGH, AUTH_MODE_BASIC_PASSTHROUGH} else InfrahubClient()
    )
    yield AppContext(client=client, config=_config)


logger = logging.getLogger(__name__)

_auth_provider = create_auth_provider(_config)

mcp: FastMCP = FastMCP(
    name="Infrahub MCP Server",
    version=version("infrahub-mcp"),
    lifespan=app_lifespan,
    auth=_auth_provider,
)

# Middleware stack — structured logging, timing, error handling, audit, read-only enforcement
configure_middleware(mcp, _config)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:  # noqa: ARG001
    """Health check endpoint for container orchestration probes.

    In shared-credential modes (``none``, ``oidc``), validates Infrahub
    connectivity via ``get_version()``. In passthrough modes, no server-side
    credentials exist so we only verify the Infrahub address is configured.
    Returns 200 when healthy, 503 when unhealthy.
    """
    address = os.environ.get("INFRAHUB_ADDRESS", "")

    if _config.auth_mode in {AUTH_MODE_TOKEN_PASSTHROUGH, AUTH_MODE_BASIC_PASSTHROUGH}:
        if not address:
            return JSONResponse(
                {"status": "unhealthy", "reason": "INFRAHUB_ADDRESS is not configured"},
                status_code=503,
            )
        return JSONResponse({"status": "healthy", "auth_mode": _config.auth_mode})

    try:
        client = InfrahubClient()
        await client.get_version()
    except ServerNotReachableError:
        logger.warning("Health check failed: Infrahub unreachable at %s", address)
        return JSONResponse(
            {"status": "unhealthy", "reason": f"Infrahub unreachable at {address}"},
            status_code=503,
        )
    except (ServerNotResponsiveError, AuthenticationError) as exc:
        logger.warning("Health check failed: %s", exc)
        return JSONResponse(
            {"status": "unhealthy", "reason": str(exc)},
            status_code=503,
        )
    except Exception:
        logger.exception("Health check failed")
        return JSONResponse({"status": "unhealthy"}, status_code=503)
    else:
        return JSONResponse({"status": "healthy"})


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics_endpoint(request: Request) -> Response:  # noqa: ARG001, RUF029
    """Metrics endpoint for monitoring (Prometheus, Grafana, Datadog).

    Returns Prometheus exposition format when ``INFRAHUB_MCP_PROMETHEUS_ENABLED=true``,
    otherwise returns JSON with request counts, error counts, cumulative latency,
    error stats from ErrorHandlingMiddleware, and cache statistics.
    """
    metrics = get_metrics()
    if metrics is None:
        return JSONResponse({"error": "metrics not configured"}, status_code=503)

    # Prometheus text format
    if _config.prometheus_enabled:
        return Response(
            content=metrics.prometheus_text(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    # JSON format with enriched data
    data = metrics.snapshot()

    # Include error stats from ErrorHandlingMiddleware
    error_mw = get_error_handling()
    if error_mw is not None:
        data["error_stats"] = error_mw.get_error_stats()

    # Include cache statistics if caching is enabled
    caching = get_caching_middleware()
    if caching is not None:
        try:
            cache_stats = caching.statistics()
            data["cache"] = cache_stats.model_dump(exclude_none=True)
        except Exception:
            logger.debug("Failed to retrieve cache statistics", exc_info=True)

    return JSONResponse(data)


@mcp.prompt()
def infrahub_agent() -> str:
    """System prompt for the Infrahub infrastructure agent."""
    access_mode = "read-only" if _config.read_only else "read and write"
    prompt = (
        f"You are an infrastructure specialist with {access_mode} access to "
        "Infrahub — a graph-based infrastructure data management platform.\n\n"
        "## Data formats\n\n"
        "Structured arrays (schema details, node attribute results) are encoded in\n"
        "**TOON** (Token-Oriented Object Notation) to reduce token usage.\n"
        "TOON declares field names once in a header, then lists rows of values.\n"
        "Treat TOON exactly like a table: the header is the column spec, each indented row is one record.\n\n"
        "## Schema discovery (always do this first)\n\n"
        "Read the ``infrahub://schema`` resource to discover available kinds before querying.\n"
        "If your client does not support MCP resources, call the ``get_schema`` tool instead —\n"
        "it provides the same data.\n\n"
        "| Resource | Tool equivalent | What it contains |\n"
        "|---|---|---|\n"
        "| `infrahub://schema` | `get_schema()` | All node kinds available in this instance |\n"
        "| `infrahub://schema/{kind}` | `get_schema(kind='...')` | Full schema + filter map for a specific kind |\n"
        "| `infrahub://graphql-schema` | *(none)* | Complete GraphQL SDL for advanced queries |\n"
        "| `infrahub://branches` | *(none)* | All branches, including your active session branch |\n\n"
        "Never guess kind names or filter keys — discover them first.\n\n"
        "## Available tools\n\n"
        "### Read\n"
        "- **`get_schema`** — discover available kinds and their attributes/filters. "
        "Use when resources are not available.\n"
        "- **`get_nodes`** — retrieve objects of a given kind, with optional filters. "
        "Pass `include_attributes=True` for full attribute data.\n"
        "- **`search_nodes`** — find nodes by partial name match.\n"
        "- **`query_graphql`** — execute a read-only GraphQL query.\n"
        '- **`find_paths`** — shortest path(s) between two nodes ("how are these connected?"). '
        "Requires Infrahub 1.10+.\n"
        "- **`find_reachable`** — nodes of given kinds reachable from a source "
        '("what\'s the blast radius?"). Requires Infrahub 1.10+.\n\n'
        'For "what is connected to X" or impact analysis, prefer `find_paths`/`find_reachable` '
        "over hand-built deep GraphQL queries."
    )

    if not _config.read_only:
        prompt += """

### Write
- **`node_upsert`** — create or update a node. Omit `id`/`hfid` to create; supply one to update.
- **`node_delete`** — delete a node by `id` or `hfid`.
- **`mutate_graphql`** — execute a GraphQL mutation.
- **`propose_changes`** — open a proposed change from your session branch to `main` for human review.
- **`reset_session_branch`** — reset or switch your session branch: call with no arguments to start \
fresh (the next write creates a new branch), or pass a branch name to switch to it (created if it \
matches the configured pattern).

## Branch-per-session workflow

All writes are branch-isolated. On your first write, a session branch is
automatically created. The default branch is never modified directly.

If your session branch is merged or deleted, the next write automatically recovers
onto a fresh branch — you do not need to restart. Use `reset_session_branch` to
switch branches deliberately.

When changes are ready: call `propose_changes(title, description)` to open a proposed change for human review.

## Safety rules

- Never modify the default branch directly.
- Prefer `node_upsert` over raw GraphQL mutations for simple attribute changes.
- Always confirm with the user before deleting nodes."""
    else:
        prompt += """

## Read-only mode

This server is running in **read-only mode**. Write operations (node creation,
updates, deletions, and GraphQL mutations) are disabled. Only queries and
schema discovery are available."""

    return prompt


# Resources — consumed as context, not as tool calls
mcp.mount(schema_resources_mcp)
mcp.mount(branches_resources_mcp)

# Prompts — parameterized workflow guides
mcp.mount(prompts_mcp)

# Tools — read tools always available
mcp.mount(graphql_mcp)
mcp.mount(nodes_mcp)
mcp.mount(session_mcp)
mcp.mount(schema_tools_mcp)
mcp.mount(traversal_mcp)

# Write tools — hidden in read-only mode
if not _config.read_only:
    mcp.mount(write_mcp)


# ---------------------------------------------------------------------------
# Token passthrough — ASGI-level header extraction
# ---------------------------------------------------------------------------


_BEARER_PREFIX = "bearer "
_BASIC_PREFIX = "basic "


class _CredentialsPassthroughASGI:
    """ASGI middleware that extracts caller credentials from an HTTP header.

    Recognised header shapes:

    - ``Bearer <token>`` or raw token → stored in the token ContextVar.
    - ``Basic <base64(user:pass)>`` → decoded into a ``(user, pass)`` tuple
      and stored in the basic-auth ContextVar.

    Non-HTTP scopes (e.g. websocket lifespan) are passed through unchanged.
    Both ContextVars are reset in ``finally`` so values cannot leak between
    requests sharing the same async context.
    """

    def __init__(self, app: "ASGIApp", *, header: str = "Authorization") -> None:
        self._app = app
        self._header = header.lower().encode("latin-1")

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:  # type: ignore[type-arg]
        token_reset = None
        basic_reset = None
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            raw = headers.get(self._header, b"").decode("latin-1").strip()
            lowered = raw[: len(_BASIC_PREFIX)].lower()
            if lowered == _BASIC_PREFIX:
                credentials = _decode_basic(raw[len(_BASIC_PREFIX) :].strip())
                if credentials is not None:
                    basic_reset = set_passthrough_basic(credentials)
            else:
                token = (
                    raw[len(_BEARER_PREFIX) :].strip() if raw[: len(_BEARER_PREFIX)].lower() == _BEARER_PREFIX else raw
                )
                if token:
                    token_reset = set_passthrough_token(token)
        try:
            await self._app(scope, receive, send)
        finally:
            if token_reset is not None:
                reset_passthrough_token(token_reset)
            if basic_reset is not None:
                reset_passthrough_basic(basic_reset)


def _decode_basic(encoded: str) -> tuple[str, str] | None:
    """Decode a Base64 ``Basic`` credential into ``(username, password)``.

    Returns ``None`` when the value is not valid Base64 or does not contain
    a ``:`` separator; the caller treats that as "no credential present".
    """
    import base64  # noqa: PLC0415
    import binascii  # noqa: PLC0415

    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None
    user, sep, password = decoded.partition(":")
    if not sep:
        return None
    return user, password


_OAUTH_DISCOVERY_SEGMENTS = (
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    "/.well-known/openid-configuration",
)


class _OAuthDiscoveryInterceptASGI:
    """ASGI middleware returning RFC 6749 JSON 404 for OAuth/OIDC discovery probes.

    MCP clients probe well-known paths for OAuth support even when the server
    doesn't use OIDC.  Without this, Starlette returns plain-text "Not Found"
    which clients fail to parse as JSON, causing ``SyntaxError`` messages.
    Only intercepts the specific OAuth/OIDC discovery endpoints (including
    path-suffixed variants like ``/mcp``) and ``/register``.
    """

    def __init__(self, app: "ASGIApp") -> None:
        self._app = app

    @staticmethod
    def _is_oauth_probe(path: str) -> bool:
        normalized = path.rstrip("/")
        if normalized == "/register":
            return True
        return any(segment in normalized for segment in _OAUTH_DISCOVERY_SEGMENTS)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:  # type: ignore[type-arg]
        if scope["type"] == "http":
            path: str = scope.get("path", "")
            if self._is_oauth_probe(path):
                response = JSONResponse(
                    {"error": "invalid_request", "error_description": "OAuth is not enabled on this server."},
                    status_code=404,
                )
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


def get_asgi_middleware() -> list[object]:
    """Return Starlette ASGI middleware for the current auth mode."""
    from starlette.middleware import Middleware as StarletteMiddleware  # noqa: PLC0415

    middlewares: list[object] = []
    if _config.auth_mode in {AUTH_MODE_TOKEN_PASSTHROUGH, AUTH_MODE_BASIC_PASSTHROUGH}:
        middlewares.append(StarletteMiddleware(_CredentialsPassthroughASGI, header=_config.token_passthrough_header))
    if _config.auth_mode != AUTH_MODE_OIDC:
        middlewares.append(StarletteMiddleware(_OAuthDiscoveryInterceptASGI))
    return middlewares
