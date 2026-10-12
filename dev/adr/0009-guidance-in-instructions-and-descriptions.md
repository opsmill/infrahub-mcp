# 9. Model Guidance in Server Instructions and Tool Descriptions

**Status:** Accepted
**Date:** 2026-10-12
**Author:** Claude Code (spec `specs/004-schema-discovery-guidance/`)

## Context

The rule "read the schema first, never guess kind names or filter keys"
lived only in the `infrahub_agent` prompt. The MCP specification defines
prompts as selected by the user and resources as included by the host
application, so neither reaches the model on its own. In a field test
through an MCP gateway, an agent needed six tool calls for a question that
needed two: it guessed a kind name and wrapped GraphQL filters in a
`filters: {...}` argument that Infrahub does not accept
([issue 191](https://github.com/opsmill/infrahub-mcp/issues/191)).

Clients differ in what they pass to the model. The Claude API MCP connector
passes only tool calls: no resources, prompts or server instructions. Some
clients pass server instructions; whether a given gateway does is not known.
Tool names and descriptions are the only text every client passes.

The tool descriptions also told the agent to read the `infrahub://schema`
resource first and to call `get_schema` only "if your client does not
support MCP resources". The resources read only the default branch, while
`get_schema` accepts a branch.

## Decision

- Model guidance is sent through two channels:
  - **Server instructions**, built by `build_instructions()` in
    `src/infrahub_mcp/instructions.py`. They state the schema-first rule,
    which tool to use for common questions, how filter keys differ between
    `get_nodes` and GraphQL, how to read TOON and the access mode. The text
    depends on `read_only` and `resources_as_tools`.
  - **Tool and parameter descriptions and error messages**, which name
    `get_schema` directly and never make the step depend on resource support.
- The `infrahub_agent` prompt includes the same instructions text, so the
  two cannot drift apart. Prompts carry workflows, not rules the model
  must always follow.
- Resources stay for hosts and users who attach context. They accept an
  optional `?branch=` so they return the same data as `get_schema`.
- `get_schema` is kept as the tool the agent uses for the schema.
- FastMCP's `ResourcesAsTools` is available behind
  `INFRAHUB_MCP_RESOURCES_AS_TOOLS` (off by default) for clients that pass
  only tools and need the branch list or the GraphQL schema.
- Prompts are not exposed as tools.
- `query_graphql` returns a specific remediation when Infrahub rejects a
  `filters` argument, because the server adds it in every client.

## Consequences

### Positive

- Agents receive the schema-first rule in every client, including clients
  that pass only tools.
- One source for the guidance text; tests check its content in all four
  variants and check that no description names a resource URI without a tool.
- No tool, argument, resource URI or prompt name changes.

### Negative

- Instructions add up to about 1,700 characters to the context of clients
  that pass them.
- Model behavior is not deterministic; the effect is checked by hand
  (3 runs, at least 2 pass) rather than by unit tests.

### Neutral

- New guidance that every agent needs belongs in `instructions.py` and, when
  it concerns one tool, in that tool's description, not only in a prompt.

## Alternatives Considered

### Keep the guidance in the prompt only

Does not reach the model unless a user selects the prompt.

### Replace `get_schema` with `ResourcesAsTools`

The generic `read_resource` tool carries no schema-first hint, needs a
`list_resources` call first and has no branch argument. Removing
`get_schema` would also break existing callers.

### Expose prompts as tools (`PromptsAsTools`)

The agent would have to know to fetch the prompt first; an agent that knows
that already has the guidance.
