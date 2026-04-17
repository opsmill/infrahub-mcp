# INFP-411 / PR 3 — Authentication (OIDC + token-passthrough)

**Parent spec:** [INFP-411.md](./INFP-411.md)
**Slice branch:** `feat/mw-auth` (off `feat/mw-readonly`)
**Status:** Not started

## Product requirement

Maps to **INFP-411 requirement #4 (Authentication — HTTP Transport)**.

Closes INFP-411 open question #8 ("MCP spec and token pass-through"): pass-through is technically outside the MCP specification but shipped in practice by other MCP servers. This slice implements it alongside OIDC so operators can choose based on their deployment model (shared service account vs. per-user identity).

## Customer problem

> The MCP server uses a single shared API token, meaning all operations appear as one service account — no per-user audit trail or permission enforcement.

Operators running a shared HTTP MCP server cannot distinguish which user made which request, cannot enforce Infrahub permissions at the MCP layer, and cannot revoke access for a single user without rotating a shared token.

## What ships in this PR

*TBD — fill in at PR open. Expected surface:*

- Three auth modes via `INFRAHUB_MCP_AUTH_MODE`: `none` (default, stdio + single-user HTTP), `oidc` (external IdP), `token-passthrough` (per-request Infrahub token in HTTP header)
- `src/infrahub_mcp/auth.py` — OIDC provider construction, passthrough token extraction, user-identity resolution
- `AuthMiddleware` + `restrict_tag` wiring so `write`-tagged tools require the configured write scopes
- Transport compatibility enforced at startup: `oidc` / `token-passthrough` require `streamable-http`; stdio with either is rejected with a clear error message
- ASGI middleware for token passthrough (extracts bearer token into a `ContextVar`) and for OAuth discovery probe responses
- `Dockerfile` + `docker-compose.yml` updates to expose the HTTP port and surface the relevant env vars
- Docs: `docs/docs/topics/authentication.mdx` (concepts), `docs/docs/guides/authentication.mdx` (setup walkthrough)

## Configuration surface

| Env var | Default | Purpose |
|---|---|---|
| `INFRAHUB_MCP_AUTH_MODE` | `none` | `none`, `oidc`, or `token-passthrough` |
| `INFRAHUB_MCP_OIDC_CONFIG_URL` | *(empty)* | OIDC discovery URL (required when `auth_mode=oidc`) |
| `INFRAHUB_MCP_OIDC_CLIENT_ID` | *(empty)* | OAuth client ID (required when `auth_mode=oidc`) |
| `INFRAHUB_MCP_OIDC_CLIENT_SECRET` | *(empty)* | Optional; omit for PKCE |
| `INFRAHUB_MCP_OIDC_BASE_URL` | *(empty)* | Public MCP server URL (required when `auth_mode=oidc`) |
| `INFRAHUB_MCP_OIDC_AUDIENCE` | *(empty)* | Token audience claim (optional) |
| `INFRAHUB_MCP_OIDC_USER_CLAIM` | `email` | JWT claim used for user identity |
| `INFRAHUB_MCP_AUTH_SCOPES_WRITE` | *(empty)* | Comma-separated OAuth scopes required for `write`-tagged tools |
| `INFRAHUB_MCP_TOKEN_PASSTHROUGH_HEADER` | `Authorization` | HTTP header carrying the Infrahub token under `token-passthrough` |

All env vars above are already parsed into `ServerConfig` in PR 1; this slice lights up the behavior.

## Validation

- Unit tests: `tests/unit/test_auth.py`, `tests/unit/test_token_passthrough.py`
- Manual: `docker compose up` with OIDC config pointing at a local IdP (e.g. Keycloak); verify user identity appears in the Infrahub audit log. Then restart with `auth_mode=token-passthrough`; verify a client-provided bearer token is used for Infrahub API calls and cleared after the request.

## Open questions / follow-ups

*TBD at PR open.*

## Links

- PR: *(fill in when opened)*
- Jira: [INFP-411](https://opsmill.atlassian.net/browse/INFP-411)
