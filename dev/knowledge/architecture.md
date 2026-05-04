# MCP Server Architecture

Overview of the infrahub-mcp server architecture. For coding standards,
see `../guidelines/python.md`.

## Server Initialization

Entry point: `src/infrahub_mcp/server.py`

The server is built on **FastMCP** and follows its composition pattern:

1. `load_config()` reads `INFRAHUB_MCP_*` env vars into a frozen
   `ServerConfig` (pydantic-settings).
2. `create_auth_provider()` builds an OIDC proxy if `auth_mode=oidc`.
3. `FastMCP(...)` is constructed with name, version, auth provider,
   and lifespan.
4. Sub-applications are mounted (tools, resources, prompts).
5. `configure_middleware(mcp, config)` attaches the middleware stack.
6. ASGI middleware wraps the app for HTTP-level concerns.

### Lifespan

`app_lifespan()` validates environment variables and creates the
`InfrahubClient` (unless in passthrough auth mode). The client and
configuration are yielded as `AppContext`, available to all tools via
FastMCP's dependency injection.

## Middleware Stack

Defined in `src/infrahub_mcp/middleware.py`. Composed once at startup
via `configure_middleware()`.

**Built-in FastMCP middleware:**
- `StructuredLoggingMiddleware` — structured log output
- `DetailedTimingMiddleware` — request duration tracking
- `ErrorHandlingMiddleware` — exception-to-MCP-error translation
- `RetryMiddleware` — transient failure retry with backoff
- `ResponseCachingMiddleware` — TTL-based caching for schema/list ops
- `RateLimitingMiddleware` — token-bucket rate limiting
- `ResponseLimitingMiddleware` — response size control
- `PingMiddleware` — HTTP session keep-alive
- `DereferenceRefsMiddleware` — JSON Schema `$ref` resolution
- `AuthMiddleware` — OAuth scope enforcement

**Custom middleware:**
- `ReadOnlyMiddleware` — blocks tools tagged `"write"` in read-only mode
- `AuditMiddleware` — structured audit log with request IDs
- `InfrahubErrorMiddleware` — translates SDK exceptions to MCP errors
- `PrometheusMiddleware` — Prometheus `/metrics` endpoint

Request correlation uses a `ContextVar` (`current_request_id`) to
propagate request IDs through the middleware stack.

## Tool Organization

Tools live in `src/infrahub_mcp/tools/`, each as a sub-application:

| Module | Purpose |
|--------|---------|
| `gql.py` | Raw GraphQL queries and mutations |
| `nodes.py` | Typed node CRUD (get, search, list) |
| `schema.py` | Schema introspection tools |
| `session.py` | Branch/session management |
| `write.py` | Write operations (upsert, delete, propose) |

Write tools are tagged `"write"` so `ReadOnlyMiddleware` and
`AuthMiddleware` can enforce access control.

## Resource Organization

Resources in `src/infrahub_mcp/resources/`:

| Module | Purpose |
|--------|---------|
| `branches.py` | Branch listing and metadata |
| `schema.py` | Schema definitions as MCP resources |

## Prompt Organization

Prompts in `src/infrahub_mcp/prompts/`:

| Module | Purpose |
|--------|---------|
| `prompts.py` | System prompts and workflow guides |

## Authentication Modes

Configured via `INFRAHUB_MCP_AUTH_MODE`:

| Mode | How it works |
|------|-------------|
| `none` | No MCP-level auth. Infrahub credentials from env vars. |
| `oidc` | Full OAuth 2.0/OIDC flow via `OIDCProxy`. MCP-level access control. |
| `token-passthrough` | Per-request Bearer token via HTTP header → `ContextVar`. |
| `basic-passthrough` | Per-request Basic auth via HTTP header → `ContextVar`. |

In passthrough modes, no `InfrahubClient` is created at startup —
each request creates its own client with the forwarded credentials.

## ASGI Middleware

HTTP-level middleware in `server.py` (wraps the FastMCP ASGI app):

- **`CredentialsPassthroughMiddleware`** — extracts Bearer/Basic
  credentials from the configured HTTP header and sets them in
  `ContextVar` for downstream use.
- **`OAuthDiscoveryInterceptMiddleware`** — intercepts
  `/.well-known/oauth-authorization-server` requests and returns
  OIDC metadata.

## Configuration

`src/infrahub_mcp/config.py` — `ServerConfig(BaseSettings)`:

- Env prefix: `INFRAHUB_MCP_`
- Frozen (immutable after construction)
- Key groups: read-only mode, branch patterns, logging, rate limiting,
  retry, caching, observability (OTEL, Prometheus), auth (OIDC fields,
  passthrough header).
- OIDC fields are validated as a complete set at `load_config()` time.
