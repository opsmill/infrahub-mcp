# 4. Tag-Based Read-Only Mode with Defense-in-Depth

**Status:** Accepted
**Date:** 2026-04-21
**Author:** @bkohler

## Context

Security-conscious teams need to restrict AI agents to read-only access before trusting them with write operations. The MCP server must completely hide write tools from agents — not just block their execution, but prevent agents from discovering they exist. This is critical because LLMs can sometimes call tools by name even if they aren't in the tool listing (from training data).

The server has a growing set of write tools (node_upsert, node_delete, propose_changes, mutate_graphql), and new write tools will be added over time. The filtering mechanism must automatically apply to new tools without code changes.

## Decision

Write tools are tagged with the `"write"` string. `ReadOnlyMiddleware` uses FastMCP's `restrict_tag()` to filter by tag. Three-layer defense-in-depth:

1. **Tool hiding** (`on_list_tools()`): Filters tools tagged `"write"` from tool listings — agents cannot discover them
2. **Call rejection** (`on_call_tool()`): Blocks execution of tagged write tools — catches direct invocation bypasses
3. **Fail-closed allowlist**: If tag resolution fails (for example, FastMCP context unavailable), only known-safe tools (`get_schema`, `query_graphql`, `get_nodes`, `search_nodes`) are permitted

Additionally, when `read_only=true`, write sub-applications are not mounted at startup — reducing the attack surface further.

## Consequences

### Positive

- Tag-based filtering automatically extends to new write tools (just add the `"write"` tag)
- Three layers ensure safety even if one layer has a bug — agents can't discover, can't invoke, and the fallback allowlist blocks unknowns
- Not mounting write sub-apps removes them from the server entirely in read-only mode

### Negative

- Developers must remember to tag new write tools with `"write"` — an untagged write tool bypasses read-only mode
- The fail-closed allowlist is a hardcoded list that needs updating when new read-only tools are added (but failing closed is the safe default)

### Neutral

- Read-only mode is server-wide, not per-user — all users either have write access or none
- The `"write"` tag is also used by `AuthMiddleware` for OIDC scope enforcement, serving double duty

## Alternatives Considered

### Hardcoded tool name list

Maintain an explicit list of write tool names to block. Rejected: fragile — new write tools would bypass read-only mode until someone updates the list. The failure mode is a security gap.

### Conditional tool registration only

Only register read tools when `read_only=true`. Rejected: doesn't protect against direct invocation by name. An agent that knows `node_upsert` exists from training data could still call it.

### Single-layer hiding only

Hide write tools from listings but don't block direct calls. Rejected: LLMs can sometimes call tools not in the listing if they know the name. Single-layer is not defense-in-depth.
