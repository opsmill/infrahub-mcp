# 3. Dual-Layer Authentication Architecture

**Status:** Accepted
**Date:** 2026-04-21
**Author:** @bkohler

## Context

The MCP server needs to support four authentication modes: `none` (development), `oidc` (production OAuth 2.0), `token-passthrough` (API token forwarding), and `basic-passthrough` (username/password forwarding). In passthrough modes, the server must extract credentials from HTTP headers and use them for Infrahub SDK calls — operating under the user's identity, not a shared service account.

FastMCP runs on Starlette with async shared thread pools. Credentials must be isolated per-request without race conditions. The server also handles two transport protocols (HTTP and stdio), where auth is only relevant for HTTP.

## Decision

Authentication operates at two layers:

1. **ASGI layer** (`_CredentialsPassthroughASGI`): Runs before the MCP protocol layer. Extracts Bearer token or Basic auth from the configurable HTTP header, stores in `ContextVar` via `set_passthrough_token()` / `set_passthrough_basic()`. Resets after each request in a `finally` block.

2. **MCP middleware layer** (`TokenPassthroughMiddleware`): Checks that the `ContextVar` has a value before allowing tool calls. Rejects with clear error if empty (fail-closed).

3. **OIDC layer**: Uses FastMCP's built-in `OIDCProxy` for the complete OAuth 2.0 flow — token exchange, JWT verification, scope extraction. OIDC controls MCP-level access; Infrahub API calls still use env var credentials.

`ContextVar` provides Task-level isolation required for async shared thread pools.

## Consequences

### Positive

- Separation of concerns: ASGI handles HTTP protocol details, MCP middleware handles business logic enforcement
- `ContextVar` guarantees per-request isolation even with concurrent async requests on shared threads
- Fail-closed: unauthenticated requests rejected before any Infrahub API call
- No custom JWT verification — `OIDCProxy` handles the crypto, reducing security surface

### Negative

- Two layers to understand and debug for credential flow
- `ContextVar` values are invisible in debuggers unless you know where to look
- OIDC mode uses env var credentials for Infrahub API (not the user's token) — per-user Infrahub identity requires passthrough modes

### Neutral

- Stdio transport bypasses auth entirely — credentials come from environment variables, which is correct for local development

## Alternatives Considered

### Request-scoped objects

Attach credentials to a request object passed through the middleware chain. Rejected: FastMCP's async model uses shared thread pools where request objects cannot be thread-local safely.

### Custom OIDC implementation

Build JWT verification, token exchange, and scope extraction from scratch. Rejected: reinventing crypto is a security risk. `OIDCProxy` from FastMCP is maintained and tested.

### Single-layer auth at ASGI only

Extract and validate credentials entirely at the ASGI layer. Rejected: MCP middleware needs to enforce per-tool access control based on OAuth scopes (e.g., write tools require `write` scope).
