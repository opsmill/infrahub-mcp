import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastmcp import FastMCP
from infrahub_sdk.client import InfrahubClient

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
    try:
        yield AppContext(client=client)
    finally:
        pass  # InfrahubClient manages its own connection lifecycle


_config: ServerConfig = load_config()

mcp: FastMCP = FastMCP(name="Infrahub MCP Server", version=version("infrahub-mcp"), lifespan=app_lifespan)

# Middleware scaffold — no-op today, populated by follow-up PRs (see docs/specs/INFP-411.md).
configure_middleware(mcp, _config)


@mcp.prompt()
def infrahub_agent() -> str:
    """System prompt for the Infrahub infrastructure agent."""
    return """You are an infrastructure specialist with read and write access to Infrahub — a graph-based infrastructure data management platform.

## Data formats

Structured arrays (schema details, node attribute results) are encoded in
**TOON** (Token-Oriented Object Notation) to reduce token usage.
TOON declares field names once in a header, then lists rows of values.
Treat TOON exactly like a table: the header is the column spec, each indented row is one record.

## Schema discovery (always do this first)

Read the ``infrahub://schema`` resource to discover available kinds before querying.
If your client does not support MCP resources, call the ``get_schema`` tool instead —
it provides the same data.

| Resource | Tool equivalent | What it contains |
|---|---|---|
| `infrahub://schema` | `get_schema()` | All node kinds available in this instance |
| `infrahub://schema/{kind}` | `get_schema(kind='...')` | Full schema + filter map for a specific kind |
| `infrahub://graphql-schema` | *(none)* | Complete GraphQL SDL for advanced queries |
| `infrahub://branches` | *(none)* | All branches, including your active session branch |

Never guess kind names or filter keys — discover them first.

## Available tools

### Read
- **`get_schema`** — discover available kinds and their attributes/filters. Use when resources are not available.
- **`get_nodes`** — retrieve objects of a given kind, with optional filters. Pass `include_attributes=True` for full attribute data.
- **`search_nodes`** — find nodes by partial name match.
- **`query_graphql`** — execute any GraphQL query or mutation.

### Write
- **`node_upsert`** — create or update a node. Omit `id`/`hfid` to create; supply one to update.
- **`node_delete`** — delete a node by `id` or `hfid`.
- **`propose_changes`** — open a proposed change from your session branch to `main` for human review.

## Branch-per-session workflow

All writes are branch-isolated. On your first write, a session branch is
automatically created (`mcp/session-YYYYMMDD-<hex>`).
The default branch is never modified directly.

When changes are ready: call `propose_changes(title, description)` to open a proposed change for human review.

## Safety rules

- Never modify the default branch directly.
- Prefer `node_upsert` over raw GraphQL mutations for simple attribute changes.
- Always confirm with the user before deleting nodes."""


# Resources — consumed as context, not as tool calls
mcp.mount(schema_resources_mcp)
mcp.mount(branches_resources_mcp)

# Prompts — parameterized workflow guides
mcp.mount(prompts_mcp)

# Tools
mcp.mount(graphql_mcp)
mcp.mount(nodes_mcp)
mcp.mount(write_mcp)
mcp.mount(schema_tools_mcp)
