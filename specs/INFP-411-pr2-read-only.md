# INFP-411 / PR 2 — Read-only mode + GraphQL read/write separation

**Parent spec:** [INFP-411.md](./INFP-411.md)
**Slice branch:** `feat/mw-readonly` (stacked on `feat/mw-config`)
**Status:** Ready for review

## Product requirement

Maps to **INFP-411 requirement #5 (Read-Only Mode)** and the GraphQL portion of **requirement #6 (Branch Targeting)** — specifically mutation blocking.

Resolves INFP-411 open question #3 ("Read-only enforcement for GraphQL: parse queries to block mutations, or disable the `query_graphql` tool entirely in read-only mode?"). This slice combines both strategies: `query_graphql` always rejects mutations at the GraphQL-parse level (safer even in read/write mode), and `ReadOnlyMiddleware` hides every `write`-tagged tool when read-only mode is on.

## Customer problem

> No way to restrict write operations — if write tools are available, they're always exposed, which is a blocker for security-conscious teams.

Operators cannot confidently expose the MCP server to AI agents until they can guarantee writes are off. `query_graphql` previously accepted mutation strings through the read path, so even a "read-only posture" server could be tricked into mutating data.

## What ships in this PR

Three layers of defense for read-only mode:

1. **Tool-level mutation parse** — `query_graphql` parses incoming GraphQL and rejects any `mutation` operation before it reaches the Infrahub client. This applies whether the server is read-only or not.
2. **Registration-time hiding** — when `INFRAHUB_MCP_READ_ONLY=true`, `server.py` skips `mcp.mount(write_mcp)`, so the four write tools (`node_upsert`, `node_delete`, `propose_changes`, `mutate_graphql`) are never registered.
3. **`ReadOnlyMiddleware`** — defense in depth. Filters `write`-tagged tools from `tools/list` responses and rejects any `tools/call` for a `write`-tagged tool. Falls back to a fail-closed allowlist (`get_schema`, `query_graphql`, `get_nodes`, `search_nodes`) when the fastmcp context is unavailable — any unknown tool is blocked.

Other changes:

- New `mutate_graphql` tool in `tools/write.py` (tagged `write`) so GraphQL mutations have a dedicated surface. Targets the session branch by default.
- System prompt (`infrahub_agent()`) adjusts its tool list and safety guidance based on `config.read_only`.
- Shared `WRITE_TAG = "write"` constant so any new write tool auto-inherits blocking.

Files:

- `src/infrahub_mcp/middleware.py` — `ReadOnlyMiddleware` + `WRITE_TAG`; registered in `configure_middleware` when `config.read_only`
- `src/infrahub_mcp/tools/gql.py` — mutation parse + rejection in `query_graphql`
- `src/infrahub_mcp/tools/write.py` — new `mutate_graphql` tool
- `src/infrahub_mcp/server.py` — conditional mount of `write_mcp`, read-only prompt variant
- `tests/unit/test_middleware.py` — new `TestReadOnlyMiddleware` covering list filtering, call rejection, fail-closed fallback, read-only allowlist
- `tests/unit/test_read_only.py` — mutation-detection parse tests mirroring `query_graphql`'s check

## Configuration surface

| Env var | Default | Purpose |
|---|---|---|
| `INFRAHUB_MCP_READ_ONLY` | `false` | When `true`, write tools are hidden and the read-only variant of the system prompt is used |

Declared and parsed in PR 1; this slice is what lights it up.

## Validation

- Unit tests: `tests/unit/test_middleware.py::TestReadOnlyMiddleware` (list filtering, call rejection, fail-closed, read-only allowlist), `tests/unit/test_read_only.py::TestMutationDetection` (query/mutation/subscription/syntax-error cases)
- Manual: start server with `INFRAHUB_MCP_READ_ONLY=true`; `tools/list` must not include `node_upsert`, `node_delete`, `propose_changes`, or `mutate_graphql`; `query_graphql` with a `mutation { ... }` string must return a `ToolError` with "Mutations are not allowed"; `infrahub_agent` prompt must include the "Read-only mode" section.

## Open questions / follow-ups

- `ReadOnlyMiddleware` is registered even for deployments that don't need it (the check is `if config.read_only`). That's fine today, but PR 4's observability work might benefit from a middleware registry/introspection layer so operators can verify which middlewares are active.
- The read-only allowlist (`get_schema`, `query_graphql`, `get_nodes`, `search_nodes`) has to stay in sync with the read tools if any are added. A follow-up could derive this list from the `retrieve`-tagged tools at startup instead of hardcoding.

## Links

- PR: *(fill in when opened)*
- Jira: [INFP-411](https://opsmill.atlassian.net/browse/INFP-411)
- Depends on: PR #75 (foundation)
