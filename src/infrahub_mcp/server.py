import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from infrahub_sdk.client import InfrahubClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from infrahub_mcp.config import ServerConfig, load_config
from infrahub_mcp.middleware import configure_middleware
from infrahub_mcp.prompts.prompts import mcp as prompts_mcp
from infrahub_mcp.resources.branches import mcp as branches_resources_mcp
from infrahub_mcp.resources.schema import mcp as schema_resources_mcp
from infrahub_mcp.tools.gql import mcp as graphql_mcp
from infrahub_mcp.tools.nodes import mcp as nodes_mcp
from infrahub_mcp.tools.schema import mcp as schema_tools_mcp
from infrahub_mcp.tools.write import mcp as write_mcp
from infrahub_mcp.utils import AppContext

_config: ServerConfig = load_config()


def _validate_env() -> None:
    """Validate required environment variables at startup and raise with clear guidance."""
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
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:  # noqa: ARG001, RUF029
    """Manage the application lifecycle: validate config, create client, yield context."""
    _validate_env()
    client = InfrahubClient()
    yield AppContext(client=client, config=_config)


logger = logging.getLogger(__name__)

mcp: FastMCP = FastMCP(
    name="Infrahub MCP Server",
    version="1.0.0",
    lifespan=app_lifespan,
)


# Middleware stack — structured logging, timing, error handling, audit, read-only enforcement
configure_middleware(mcp, _config)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:  # noqa: ARG001, RUF029
    """Health check endpoint for container orchestration probes.

    Uses the SDK's ``get_version()`` to validate Infrahub connectivity.
    Returns 200 when healthy, 503 when Infrahub is unreachable.
    """
    try:
        client = InfrahubClient()
        client.get_version()
        return JSONResponse({"status": "healthy"})
    except Exception:
        logger.exception("Health check failed")
        return JSONResponse({"status": "unhealthy"}, status_code=503)


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
        "- **`get_schema`** — discover available kinds and their attributes/filters. Use when resources are not available.\n"
        "- **`get_nodes`** — retrieve objects of a given kind, with optional filters. Pass `include_attributes=True` for full attribute data.\n"
        "- **`search_nodes`** — find nodes by partial name match.\n"
        "- **`query_graphql`** — execute a read-only GraphQL query."
    )

    if not _config.read_only:
        prompt += """

### Write
- **`node_upsert`** — create or update a node. Omit `id`/`hfid` to create; supply one to update.
- **`node_delete`** — delete a node by `id` or `hfid`.
- **`mutate_graphql`** — execute a GraphQL mutation.
- **`propose_changes`** — open a proposed change from your session branch to `main` for human review.

## Branch-per-session workflow

All writes are branch-isolated. On your first write, a session branch is
automatically created. The default branch is never modified directly.

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
mcp.mount(schema_tools_mcp)

# Write tools — hidden in read-only mode
if not _config.read_only:
    mcp.mount(write_mcp)
