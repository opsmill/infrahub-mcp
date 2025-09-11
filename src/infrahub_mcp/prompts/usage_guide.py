from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import PromptMessage, TextContent
from pydantic import Field

mcp = FastMCP(name="Infrahub Usage Prompts", version="1.0.0")


@mcp.prompt(
    name="answer_infra_question",
    description="Answer infra questions by reading branch-scoped schema resources first, then using mapping+filters+query tools.",
    tags={"schema", "query", "infra"},
)
def answer_infra_question(
    question: Annotated[str, Field(description="User question about the infra")],
    kind_hint: Annotated[str | None, Field(default=None, description="Optional guess/hint for the schema kind")],
    fields: Annotated[list[str] | None, Field(default=None, description="Optional list of fields to return")],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to retrieve the objects from. Defaults to None (uses default branch)."),
    ],
) -> PromptMessage:
    # Resolve URIs (supports your 'current' static resource if you added it; otherwise set a default branch)
    resolved_branch = branch or "current"
    base_uri = f"infrahub://branch/{resolved_branch}/schema"
    kind_uri = f"infrahub://branch/{resolved_branch}/schema/{{target_kind}}"
    fields_display = fields if fields is not None else []

    txt = f"""
You are an infrastructure specialist.

User question: {question}

PIPELINE (follow exactly):

STEP 0 — Read schema (resources)
- Read: {base_uri}
- After choosing a kind, also read: {kind_uri}
- If any resource returns status="error", use its remediation and stop.

STEP 1 — Identify target kind
- Try tool `schema_get_mapping(question)` to map the question to a kind.
- If that fails, infer from the schema resource (names/attributes/relationships).
- Use kind_hint if helpful: "{kind_hint or ""}". Decide a single target_kind and note any assumptions briefly.

STEP 2 — Validate fields
- From the kind schema, validate requested fields: {fields_display or "[]"}
- If a requested field is missing, pick the closest valid field and note the substitution.

STEP 3 — Build filters
- Call tool `get_node_filters(kind=target_kind{f", branch={branch!r}" if branch else ""})` to learn valid filters.
- Translate natural-language constraints in the question into the tool's filter parameters.

STEP 4 — Query data
- Call tool `get_objects(kind=target_kind, fields=<validated fields>, filters=<built filters>{f", branch={branch!r}" if branch else ""})`.
- If status="error", surface remediation and stop.

STEP 5 — Answer + provenance
- Provide a concise answer (bullets are fine).
- Add a short "Provenance" listing:
  - resources read (URIs),
  - tools called (name + key args),
  - assumptions/substitutions.

RULES
- Read resources before calling tools.
- Only use fields present in the kind schema.
- Keep outputs concise and relevant.
"""
    return PromptMessage(role="user", content=TextContent(type="text", text=txt))
