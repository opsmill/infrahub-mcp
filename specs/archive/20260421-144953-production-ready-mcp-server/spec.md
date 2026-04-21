# Feature Specification: Production-Ready MCP Server (INFP-411)

**Feature Branch**: `feat/add-middleware`
**Created**: 2026-04-21
**Status**: Draft
**Jira**: INFP-411
**Input**: User description: "Build deployment packaging, authentication, operational controls, and documentation for the Infrahub MCP server as a first-class, production-ready component of Infrahub deployments."

## Clarifications

### Session 2026-04-21

- Q: Which MCP transport protocols are supported? → A: Both HTTP (Streamable HTTP) and stdio. Auth passthrough and health/metrics endpoints are HTTP-only; stdio uses environment variable credentials.
- Q: What form does the audit log take? → A: Structured log output only — audit events emitted as JSON log entries to stdout, aggregated externally. No dedicated audit file or webhook; the server remains stateless.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Middleware Observability Stack (Priority: P1)

An operator deploying the MCP server needs structured logging, request correlation, performance metrics, and health checks to operate the server in production with confidence — matching the observability standards of the Infrahub server itself.

**Why this priority**: Without observability, operators cannot monitor, debug, or alert on the MCP server in production. This is the foundation all other features depend on.

**Independent Test**: Can be fully tested by starting the server, sending tool calls, and verifying structured log output, `/health` endpoint responses, and `/metrics` endpoint output.

**Acceptance Scenarios**:

1. **Given** a running MCP server, **When** any tool call is processed, **Then** a structured JSON log entry is emitted with request ID, tool name, duration, and token estimates.
2. **Given** a running MCP server, **When** `GET /health` is called, **Then** a JSON response indicates server status and Infrahub backend connectivity.
3. **Given** a running MCP server with `prometheus_enabled=true`, **When** `GET /metrics` is called, **Then** Prometheus-format metrics are returned including request counts, latencies, and error rates.
4. **Given** a running MCP server, **When** multiple concurrent requests arrive, **Then** each request has a unique correlation ID propagated through the entire middleware stack.
5. **Given** a running MCP server with `otel_enabled=true`, **When** tool calls are processed, **Then** OpenTelemetry spans are emitted for each middleware layer and tool execution.

---

### User Story 2 — Pass-Through Authentication (Priority: P1)

A user points their AI tool (Claude Desktop, Cursor) at the MCP server with their personal Infrahub API token or username/password. The MCP server authenticates them against Infrahub and operates under their identity — preserving Infrahub's permission model and audit trail. No shared service account.

**Why this priority**: Security-conscious teams will not adopt the MCP server without per-user authentication. This is a hard blocker for enterprise deployment.

**Independent Test**: Can be tested by configuring `auth_mode=token-passthrough`, sending requests with and without a valid Infrahub API token, and verifying that authenticated requests succeed while unauthenticated requests are rejected.

**Acceptance Scenarios**:

1. **Given** `auth_mode=token-passthrough`, **When** a client sends a request with a valid Infrahub API token in the configured header, **Then** the MCP server uses that token for all Infrahub SDK calls and the operation succeeds under the user's identity.
2. **Given** `auth_mode=token-passthrough`, **When** a client sends a request without a token, **Then** the request is rejected with a clear error before any tool execution occurs.
3. **Given** `auth_mode=basic-passthrough`, **When** a client sends Infrahub username/password via Basic auth header, **Then** the MCP server creates a per-request SDK client with those credentials.
4. **Given** `auth_mode=oidc`, **When** a client authenticates via OAuth 2.0 / OIDC flow, **Then** the MCP server validates the JWT, extracts user identity from the configured claim, and enforces scope-based access control on write operations.
5. **Given** `auth_mode=none`, **When** any client connects, **Then** the server uses the shared environment variable credentials (development mode only).
6. **Given** any passthrough auth mode, **When** credentials are processed, **Then** they are stored in a `ContextVar` (never global state) and never appear in logs.

---

### User Story 3 — Read-Only Mode (Priority: P2)

An operator enables read-only mode (`INFRAHUB_MCP_READ_ONLY=true`) so that AI agents can query infrastructure data but cannot create, modify, or delete any objects. Write tools are completely hidden from the MCP client — agents cannot even discover them.

**Why this priority**: This is the trust gate for security-conscious teams. Many organizations want to start with read-only access before enabling writes.

**Independent Test**: Can be tested by starting the server with `read_only=true`, listing available tools, and confirming write tools (node_upsert, node_delete, propose_changes, mutate_graphql) are absent.

**Acceptance Scenarios**:

1. **Given** `read_only=true`, **When** a client lists available tools, **Then** tools tagged `"write"` (node_upsert, node_delete, propose_changes, mutate_graphql) are not included in the response.
2. **Given** `read_only=true`, **When** a client attempts to call a write tool by name, **Then** the call is rejected with a clear "read-only mode" error.
3. **Given** `read_only=false` (default), **When** a client lists available tools, **Then** all tools including write tools are visible and callable.
4. **Given** `read_only=true`, **When** the server starts, **Then** write sub-applications are not mounted, reducing the attack surface.

---

### User Story 4 — Auto Branching with Naming Convention (Priority: P2)

Write operations are automatically isolated to a session branch (created on first write) so that production data on the default branch is never modified directly. The branch name follows a configurable pattern with support for date, random hex, and user identity placeholders.

**Why this priority**: Branch isolation is what makes write operations safe. Without it, an AI agent could directly modify production infrastructure data.

**Independent Test**: Can be tested by configuring a branch pattern, executing a write tool, and verifying a new branch was created with the expected name format.

**Acceptance Scenarios**:

1. **Given** `branch_pattern=mcp/session-{date}-{hex}`, **When** the first write operation occurs in a session, **Then** a new branch is created matching the pattern (e.g., `mcp/session-20260421-a3f2`) and the write targets that branch.
2. **Given** `branch_pattern=mcp/{user}-{date}` with OIDC auth, **When** user `jane@example.com` performs a write, **Then** a branch named `mcp/jane-20260421` is created with the user identity extracted from the OIDC JWT claim.
3. **Given** a session with an active branch, **When** subsequent write operations occur, **Then** they target the existing session branch (no new branch created).
4. **Given** a branch pattern that collides with an existing branch, **When** creation is attempted, **Then** the system retries with a new `{hex}` value (up to `max_branch_retries` attempts).
5. **Given** a write operation targeting the instance's default branch (e.g., `main`), **Then** the operation is blocked with a clear error directing the user to use `propose_changes` instead.
6. **Given** any session, **When** `get_session_info` is called, **Then** the response includes the active session branch name and status.

---

### Edge Cases

- What happens when the Infrahub backend is unreachable during a tool call? → `InfrahubConnectionMiddleware` translates SDK connection errors to MCP-standard errors.
- What happens when a passthrough token is invalid or expired? → The Infrahub SDK raises `AuthenticationError`, translated to an MCP auth error.
- What happens when the branch name pattern produces invalid git ref characters? → Branch names are validated against allowed characters (alphanumeric, hyphens, underscores, dots, slashes); invalid characters are rejected at config validation time.
- What happens when rate limiting is exceeded? → `RateLimitingMiddleware` returns an MCP error with retry-after guidance.
- What happens when response size exceeds limits? → `ResponseLimitingMiddleware` / `StrictResponseLimitingMiddleware` truncates or rejects oversized responses.
- What happens when OIDC is configured with incomplete fields? → `load_config()` fails fast at startup with a clear message listing the missing env vars.
- What happens when a stdio client attempts to use passthrough auth? → Stdio transport ignores passthrough auth settings; credentials come from environment variables only.
- Where do audit events go? → Structured JSON to stdout only. External log aggregation (ELK, Loki, CloudWatch) handles retention and querying.

## Requirements *(mandatory)*

### Functional Requirements

**Middleware & Observability**:
- **FR-001**: Server MUST provide structured JSON logging for all tool calls with request ID, tool name, duration, and token estimates.
- **FR-002**: Server MUST expose a `/health` endpoint that verifies Infrahub backend connectivity and returns structured status.
- **FR-003**: Server MUST support optional Prometheus metrics at `/metrics` (configurable via `prometheus_enabled`).
- **FR-004**: Server MUST support optional OpenTelemetry tracing (configurable via `otel_enabled`).
- **FR-005**: Server MUST assign a unique request ID to each operation, propagated via `ContextVar` through the middleware stack.
- **FR-006**: Server MUST provide configurable rate limiting (token-bucket algorithm, `rate_limit_rps` and `rate_limit_burst`).
- **FR-007**: Server MUST provide configurable response size limiting to prevent oversized responses.
- **FR-008**: Server MUST provide configurable retry with backoff for transient Infrahub failures.
- **FR-009**: Server MUST provide configurable response caching for schema and list operations (`cache_enabled`, TTL settings).

**Authentication**:
- **FR-010**: Server MUST support four authentication modes: `none`, `oidc`, `token-passthrough`, `basic-passthrough`.
- **FR-011**: In `token-passthrough` mode, server MUST extract the Bearer token from a configurable HTTP header and use it for all Infrahub SDK calls in that request.
- **FR-012**: In `basic-passthrough` mode, server MUST extract username/password from Basic auth header and create a per-request SDK client.
- **FR-013**: In `oidc` mode, server MUST handle the full OAuth 2.0 / OIDC authorization code flow, validate JWTs, and enforce scope-based write access.
- **FR-014**: In passthrough modes, server MUST reject tool calls when no credential is present (fail-closed).
- **FR-015**: Server MUST store per-request credentials in `ContextVar`, never in global state.
- **FR-016**: When `auth_mode=oidc`, server MUST return well-formed JSON error responses (RFC 6749) for `/.well-known/oauth-authorization-server` probes to prevent client parse errors. OIDC discovery metadata is delegated to the upstream provider via FastMCP's `OIDCProxy`.

**Read-Only Mode**:
- **FR-017**: When `read_only=true`, server MUST hide all tools tagged `"write"` from tool listing.
- **FR-018**: When `read_only=true`, server MUST reject calls to write tools even if invoked by name.
- **FR-019**: When `read_only=true`, server MUST NOT mount write sub-applications at startup.
- **FR-020**: Server MUST use a tag-based mechanism (not hardcoded tool names) to identify write tools, so new write tools are automatically restricted.

**Auto Branching**:
- **FR-021**: Server MUST support a configurable `branch_pattern` with `{date}`, `{hex}`, and `{user}` placeholders.
- **FR-022**: Server MUST lazily create the session branch on the first write operation (not at session start).
- **FR-023**: Server MUST retry branch creation with a new `{hex}` value on name collision (up to `max_branch_retries`).
- **FR-024**: Server MUST block direct writes to the instance's default branch.
- **FR-025**: Server MUST extract user identity from OIDC JWT claims for the `{user}` placeholder, sanitized to valid git ref characters.
- **FR-026**: Server MUST provide a `get_session_info` tool that reports the active session branch and status.

**Transport**:
- **FR-027**: Server MUST support both HTTP (Streamable HTTP) and stdio transport protocols. Transport is determined by entry point (`uvicorn` for HTTP, direct invocation for stdio) via FastMCP's built-in transport support — no explicit transport configuration flag is required.
- **FR-028**: Auth passthrough modes (`token-passthrough`, `basic-passthrough`, `oidc`) are HTTP-only; stdio transport operates with environment variable credentials (`auth_mode=none` equivalent).
- **FR-029**: Health check (`/health`) and metrics (`/metrics`) endpoints are HTTP-only and not available in stdio mode.

**Audit Logging**:
- **FR-030**: Audit events (write operations, authentication outcomes, access denials) MUST be emitted as structured JSON log entries to stdout.
- **FR-031**: The server MUST NOT maintain persistent audit state — all audit data flows through the structured logging pipeline for external aggregation.

**Configuration**:
- **FR-032**: All server configuration MUST be loaded from `INFRAHUB_MCP_*` environment variables via pydantic-settings.
- **FR-033**: Configuration MUST be validated at startup; invalid or incomplete configuration MUST cause a fail-fast startup error with clear guidance.

### Key Entities

- **ServerConfig**: Immutable configuration loaded from environment variables. Controls all server behavior (auth mode, read-only, branch pattern, rate limits, caching, observability).
- **AppContext**: Runtime context carrying the `InfrahubClient` and `ServerConfig`, shared via FastMCP lifespan.
- **Session Branch**: An automatically created Infrahub branch scoped to an agent session, isolating write operations from the default branch.
- **Middleware Stack**: Ordered chain of interceptors composed once at startup via `configure_middleware()`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All tool calls produce structured log entries with correlation IDs — verifiable by parsing JSON log output.
- **SC-002**: `/health` endpoint responds within 2 seconds and accurately reflects Infrahub backend connectivity.
- **SC-003**: Authenticated users operate under their own identity — verifiable by checking Infrahub audit trail shows the user's token, not a shared service account.
- **SC-004**: Unauthenticated requests in passthrough modes are rejected before any Infrahub API call is made — verifiable by checking no SDK calls occur without credentials.
- **SC-005**: In read-only mode, 100% of write tools are hidden from tool listing and rejected on direct invocation.
- **SC-006**: Session branches are created with the correct naming pattern on first write — verifiable by checking Infrahub branch list after a write operation.
- **SC-007**: Direct writes to the default branch are blocked 100% of the time.
- **SC-008**: Configuration errors produce clear, actionable error messages within 1 second of server startup.
- **SC-009**: All new features have corresponding test coverage (happy path + edge cases).

## Assumptions

- The Infrahub SDK (`infrahub-sdk`) supports per-request authentication via API token and username/password — confirmed by existing SDK usage.
- FastMCP's middleware composition pattern supports the full middleware chain required (logging, caching, auth, rate limiting, etc.) — confirmed by existing implementation.
- The `OIDCProxy` from `fastmcp.server.auth` handles the complete OAuth 2.0 / OIDC flow — confirmed by auth.py integration.
- Container image packaging, Docker Compose integration, and Helm chart work are tracked separately and will be handled in the infrahub-helm and main infrahub repositories — not in scope for this spec.
- Documentation (deployment guide, agent integration examples) will be created as a follow-up effort after the core features stabilize.
- Write tools (node_upsert, node_delete, propose_changes, mutate_graphql) are being developed in parallel by Benoit — this spec assumes they exist and are tagged `"write"`.
