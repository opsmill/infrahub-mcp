"""Parameterized MCP prompts for guided Infrahub workflows."""

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.prompts import Message
from pydantic import Field

mcp: FastMCP = FastMCP(name="Infrahub Prompts")


@mcp.prompt()
def answer_infra_question(
    question: Annotated[str, Field(description="The infrastructure question to answer.")],
    kind_hint: Annotated[
        str | None,
        Field(default=None, description="Known or guessed schema kind. Skips the discovery step if provided."),
    ] = None,
    fields: Annotated[
        str | None,
        Field(default=None, description="Comma-separated attribute names to include in the result."),
    ] = None,
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ] = None,
) -> list[Message]:
    """Read-only pipeline for answering infrastructure questions using Infrahub data."""
    branch_note = f" on branch `{branch}`" if branch else ""
    branch_arg = f', branch="{branch}"' if branch else ""
    fields_note = f"\n\nThe user is specifically interested in these fields: **{fields}**." if fields else ""

    if kind_hint:
        step1 = (
            f"The target kind is **{kind_hint}** (provided by the user). "
            f"Skip catalog discovery and go directly to the schema detail."
        )
        kind_ref = kind_hint
    else:
        step1 = (
            "Read the resource `infrahub://schema` to browse the full catalog of available kinds. "
            "Identify which kind best matches the question."
        )
        kind_ref = "{kind}"

    include_attrs = ", include_attributes=True" if fields else ""

    body = f"""Answer the following infrastructure question{branch_note}:

> {question}{fields_note}

Follow these steps in order:

### Step 1 — Identify the kind
{step1}

### Step 2 — Read the schema detail
Read the resource `infrahub://schema/{kind_ref}` to understand:
- Available **attributes** and their types
- Available **relationships** and their peers
- The complete **filter map** (all valid filter keys for `get_nodes`)

### Step 3 — Retrieve the data
Call `get_nodes(kind="{kind_ref}"{branch_arg}{include_attrs})` \
with appropriate filters derived from the schema.
If you need a fuzzy lookup instead, \
use `search_nodes(query=..., kind="{kind_ref}"{branch_arg})`.

### Step 4 — Traverse relationships if needed
If the answer requires data from related nodes, use `query_graphql` with a targeted GraphQL query.

### Step 5 — Answer with provenance
Provide a clear answer and cite:
- The **kind** queried
- The **filters** applied (if any)
- The **branch** used

**Note:** When `include_attributes=True` is used, attribute results are encoded in
TOON (Token-Oriented Object Notation) tabular format.
The header declares field names once; each indented row is one record."""

    return [Message(body)]


@mcp.prompt()
def make_infra_change(
    description: Annotated[str, Field(description="What infrastructure change to make.")],
    kind: Annotated[
        str | None,
        Field(default=None, description="Target schema kind for the change."),
    ] = None,
    branch: Annotated[
        str | None,
        Field(default=None, description="Existing branch to target. A session branch is auto-created if omitted."),
    ] = None,
) -> list[Message]:
    """Write workflow for making infrastructure changes through Infrahub."""
    kind_note = f" targeting kind **{kind}**" if kind else ""
    branch_note = f" on branch `{branch}`" if branch else ""
    placeholder = "{kind}"  # noqa: RUF027
    kind_ref = kind or placeholder
    catalog_hint = (
        "" if kind else "If you are unsure which kind to target, read `infrahub://schema` first to browse the catalog."
    )

    body = f"""Make the following infrastructure change{kind_note}{branch_note}:

> {description}

Follow these steps in order:

### Step 1 — Understand the schema
Read `infrahub://schema/{kind_ref}` to confirm:
- Required vs optional attributes
- Valid attribute names and types
- Relationship structure

{catalog_hint}

### Step 2 — Apply the change
- To **create or update** a node: call `node_upsert(kind="{kind_ref}", data={{...}})`.
  - Omit `id`/`hfid` to create; supply one to update an existing node.
- To **delete** a node: call `node_delete(kind="{kind_ref}", id=... or hfid=...)`.
  - **Always confirm with the user before deleting.**

### Step 3 — Verify the change
Read back the affected nodes using `get_nodes` on the session branch \
to confirm the change was applied correctly.

### Step 4 — Propose for review
Call `propose_changes(title=..., description=...)` to open a proposed change for human review.

### Safety reminders
- All writes target a **session branch** (auto-created on first write as `mcp/session-YYYYMMDD-<hex>`).
- The default branch is **never modified directly**.
- You can continue making changes after calling `propose_changes`.
- Only scalar attributes are supported in `node_upsert` data — \
use `query_graphql` for relationship mutations."""

    return [Message(body)]


@mcp.prompt()
def explore_schema(
    kind: Annotated[
        str | None,
        Field(default=None, description="Specific kind to explore. Omit to browse the full catalog."),
    ] = None,
) -> list[Message]:
    """Schema discovery prompt for exploring Infrahub's data model."""
    if kind:
        body = f"""Explore the schema for kind **{kind}**.

### Steps
1. Read the resource `infrahub://schema/{kind}` to get the full definition.
2. Summarize:
   - **Attributes**: name, type, whether optional
   - **Relationships**: name, peer kind, cardinality, whether optional
   - **Filters**: all valid filter keys for `get_nodes`

The schema detail is encoded in TOON tabular format —
the header declares field names once, each indented row is one record."""
    else:
        kind_placeholder = "{kind}"  # noqa: RUF027
        body = f"""Explore the full Infrahub schema catalog.

### Steps
1. Read the resource `infrahub://schema` to list all available kinds and their labels.
2. Provide a summary organized by namespace or domain.
3. For any kind the user asks about in follow-up, read `infrahub://schema/{kind_placeholder}` \
for the full detail including attributes, relationships, and filters."""

    return [Message(body)]
