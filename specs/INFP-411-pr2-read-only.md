# INFP-411 / PR 2 — Read-only mode + GraphQL read/write separation

**Parent spec:** [INFP-411.md](./INFP-411.md)
**Slice branch:** `feat/mw-readonly` (off `feat/mw-config`)
**Status:** Not started

## Product requirement

Maps to **INFP-411 requirement #5 (Read-Only Mode)** and the GraphQL portion of **requirement #6 (Branch Targeting)** — specifically the "mutation blocking" piece.

Addresses INFP-411 open question #3 ("Read-only enforcement for GraphQL: parse queries to block mutations, or disable the `query_graphql` tool entirely in read-only mode?"). This slice chooses the simpler and safer path: split `query_graphql` (read) from `mutate_graphql` (write), tag write tools, and filter by tag in a fail-closed `ReadOnlyMiddleware`.

## Customer problem

> No way to restrict write operations — if write tools are available, they're always exposed, which is a blocker for security-conscious teams.

Operators cannot confidently expose the MCP server to AI agents until they can guarantee writes are off. A shared `INFRAHUB_API_TOKEN` means every agent runs with the same blast radius.

## What ships in this PR

- `INFRAHUB_MCP_READ_ONLY=true` env var (already declared in `ServerConfig` in PR 1) becomes load-bearing
- Split `query_graphql` (read) and `mutate_graphql` (write) tools in `src/infrahub_mcp/tools/gql.py` / `tools/write.py`
- Write tools tagged `write` via FastMCP tag metadata
- `ReadOnlyMiddleware` in `src/infrahub_mcp/middleware.py` — fail-closed, filters by `write` tag so new write tools auto-inherit protection
- Read-only behavior reflected in the system prompt (`infrahub_agent()`)

## Configuration surface

| Env var | Default | Purpose |
|---|---|---|
| `INFRAHUB_MCP_READ_ONLY` | `false` | When `true`, write tools are hidden and GraphQL mutations are blocked |

## Validation

- Unit tests: `tests/unit/test_read_only.py`
- Manual: start server with `INFRAHUB_MCP_READ_ONLY=true`; verify `node_upsert`/`node_delete`/`mutate_graphql`/`propose_changes` are not listed; verify `query_graphql` with a mutation string is rejected

## Open questions / follow-ups

*None identified at this time.*

## Links

- PR: *(fill in when opened)*
- Jira: [INFP-411](https://opsmill.atlassian.net/browse/INFP-411)
