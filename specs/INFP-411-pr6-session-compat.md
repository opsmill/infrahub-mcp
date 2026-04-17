# INFP-411 / PR 6 — Session / compat (branch-per-session, DereferenceRefs, Ping)

**Parent spec:** [INFP-411.md](./INFP-411.md)
**Slice branch:** `feat/mw-compat` (off `feat/mw-auth`, merges to `stable` independently)
**Status:** Not started

## Product requirement

Maps to **INFP-411 requirement #6 (Branch Targeting for Write Operations)** and closes INFP-411 open question #4 ("Branch naming convention").

Also includes two small client-compat middlewares that belong with the operational polish: `DereferenceRefsMiddleware` (inlines JSON Schema `$ref` for VS Code Copilot compatibility) and `PingMiddleware` (periodic keepalive for long-running HTTP sessions).

## Customer problem

> The MCP server uses a single shared API token, meaning all operations appear as one service account — no per-user audit trail or permission enforcement. … No way to control which branch write operations target without modifying code.

Without branch isolation, every agent's first write lands on the default branch — production data — which blocks security-conscious teams from enabling writes at all. The pattern from INFP-411 ("create a new branch per agent session, blocked from writing to the default branch, aligns with the proposed-changes workflow") is the feature that makes write access safe to expose.

Client-compat issues (VS Code Copilot failing to parse schemas with `$ref`, long-running HTTP sessions dropping mid-conversation) aren't in the INFP-411 spec but are reported by early adopters and belong in the Phase 2 polish.

## What ships in this PR

- Branch-per-session logic in `src/infrahub_mcp/utils.py`: `get_or_create_session_branch` honors `INFRAHUB_MCP_BRANCH_PATTERN` with `{date}`, `{hex}`, `{user}` placeholders
- Collision retry up to `INFRAHUB_MCP_MAX_BRANCH_RETRIES` attempts if the generated name already exists
- `DereferenceRefsMiddleware` — inlines `$ref` in JSON schemas when `INFRAHUB_MCP_DEREFERENCE_SCHEMAS=true`
- `PingMiddleware` — periodic keepalive when `INFRAHUB_MCP_PING_INTERVAL_MS > 0` on HTTP transport
- Registration wiring in `configure_middleware(mcp, config)`
- `tests/unit/test_branch_pattern.py` + compat middleware tests

## Configuration surface

| Env var | Default | Purpose |
|---|---|---|
| `INFRAHUB_MCP_BRANCH_PATTERN` | `mcp/session-{date}-{hex}` | Branch naming pattern; supports `{date}`, `{hex}`, `{user}` placeholders; treated as a fixed name if no placeholders |
| `INFRAHUB_MCP_MAX_BRANCH_RETRIES` | `5` | Max collision retries (1–20) |
| `INFRAHUB_MCP_DEREFERENCE_SCHEMAS` | `false` | Inline `$ref` in JSON schemas for client compatibility |
| `INFRAHUB_MCP_PING_INTERVAL_MS` | `0` | Ping interval in ms (0 = disabled; 1–300000 otherwise) |

All env vars above are already parsed into `ServerConfig` in PR 1.

## Validation

- Unit tests: `tests/unit/test_branch_pattern.py`
- Manual: start server with `INFRAHUB_MCP_BRANCH_PATTERN=mcp/{user}/{date}`; trigger a write; verify branch name in Infrahub. Set `INFRAHUB_MCP_DEREFERENCE_SCHEMAS=true`; list tools from VS Code Copilot; verify schema rendering. Set `INFRAHUB_MCP_PING_INTERVAL_MS=30000` on an HTTP session; idle for a minute; verify connection stays alive.

## Open questions / follow-ups

- Resolve INFP-411 open question #4 by documenting the chosen default (`mcp/session-{date}-{hex}`) and the placeholder grammar in this spec when the PR opens.

## Links

- PR: *(fill in when opened)*
- Jira: [INFP-411](https://opsmill.atlassian.net/browse/INFP-411)
