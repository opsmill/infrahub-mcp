# Research: Production-Ready MCP Server (INFP-411)

**Note**: This is a retrospective research document. All decisions below have already been implemented.

## R1: Middleware Stack Ordering

**Decision**: 17-layer middleware stack composed once at startup via `configure_middleware()`, ordered from outermost (first to run) to innermost (closest to tool execution).

**Stack order**:
1. `RequestIdMiddleware` — assigns correlation ID via `ContextVar`
2. `MetricsMiddleware` — Prometheus counters and histograms
3. `OTelTracingMiddleware` — OpenTelemetry span creation
4. `ErrorHandlingMiddleware` — exception-to-MCP-error translation
5. `InfrahubConnectionMiddleware` — SDK connection error handling
6. `RetryMiddleware` — transient failure retry with backoff
7. `RateLimitingMiddleware` — token-bucket rate limiting
8. `StructuredLoggingMiddleware` — JSON structured logs
9. `DetailedTimingMiddleware` — per-operation timing breakdown
10. `ResponseCachingMiddleware` — TTL-based caching for schema/list
11. `DereferenceRefsMiddleware` — JSON Schema `$ref` resolution
12. `PingMiddleware` — HTTP session keep-alive
13. `AuthMiddleware` — OAuth scope enforcement
14. `TokenPassthroughMiddleware` — credential presence enforcement
15. `ReadOnlyMiddleware` — write tool filtering
16. `AuditMiddleware` — structured audit log for write operations
17. `ResponseLimitingMiddleware` — response size control (innermost)

**Rationale**: Observability (request ID, metrics, tracing) must wrap everything to capture the full request lifecycle including errors. Error handling sits before retry to catch non-retryable failures early. Auth sits after caching so cached responses don't bypass auth (FastMCP caching is key-based and auth-aware). ReadOnly sits after auth so permission checks happen before tool filtering. Response limiting is innermost as a final safety gate.

**Alternatives considered**:
- Scatter middleware across modules (rejected: hard to reason about ordering, impossible to debug)
- Per-request middleware construction (rejected: unnecessary overhead, stack is config-dependent not request-dependent)

## R2: Dual-Layer Authentication Architecture

**Decision**: Authentication operates at two layers — ASGI middleware extracts credentials from HTTP headers, MCP middleware enforces their presence.

**Design**:
- ASGI layer (`_CredentialsPassthroughASGI`): Extracts Bearer token or Basic auth from the configurable HTTP header, stores in `ContextVar` via `set_passthrough_token()` / `set_passthrough_basic()`. Runs before the MCP protocol layer.
- MCP layer (`TokenPassthroughMiddleware`): Checks that the `ContextVar` has a value before allowing tool calls. Rejects with clear error if empty (fail-closed).
- OIDC layer (`OIDCProxy` from fastmcp): Handles the complete OAuth 2.0 flow. OIDC controls MCP-level access; Infrahub API calls still use env var credentials.

**Rationale**: ContextVar provides Task-level isolation (required for async shared thread pools). The dual-layer design separates concerns: ASGI handles HTTP protocol details, MCP middleware handles business logic enforcement. Using FastMCP's built-in OIDCProxy avoids custom JWT verification and reduces the security surface.

**Alternatives considered**:
- Request-scoped objects (rejected: FastMCP's async model uses shared thread pools where request objects can't be thread-local)
- Custom OIDC implementation (rejected: reinventing crypto is a security risk; OIDCProxy handles token exchange, JWT verification, and scope extraction)
- Single-layer auth at ASGI only (rejected: MCP middleware needs to enforce per-tool access control based on OAuth scopes)

## R3: Tag-Based Read-Only Mode with Defense-in-Depth

**Decision**: Write tools are tagged with `"write"` string. `ReadOnlyMiddleware` uses `restrict_tag()` from FastMCP to filter by tag. Three-layer defense: tool hiding + call rejection + fail-closed allowlist fallback.

**Design**:
- `on_list_tools()`: Filters tools tagged `"write"` from tool listings — LLMs cannot discover them
- `on_call_tool()`: Blocks execution of tagged write tools — catches direct invocation bypasses
- Fail-closed allowlist: If tag resolution fails, only known-safe tools (`get_schema`, `query_graphql`, `get_nodes`, `search_nodes`) are allowed

**Rationale**: Tag-based filtering automatically extends to new write tools (just add the `"write"` tag). Defense-in-depth because: (1) hiding from LLMs is the primary gate (agents can't use what they don't see), (2) call rejection catches programmatic bypasses, (3) fail-closed allowlist ensures safety even if the tag system has a bug.

**Alternatives considered**:
- Hardcoded tool name list (rejected: fragile, new write tools would bypass read-only until someone updates the list)
- Conditional tool registration only (rejected: doesn't protect against direct invocation by name)
- Single-layer hiding only (rejected: LLMs can sometimes call tools not in the listing if they know the name from training data)

## R4: Lazy Session Branch Creation with Collision Retry

**Decision**: Session branches are created lazily on first write operation (not at session start). Branch names use a configurable pattern with `{date}`, `{hex}`, `{user}` placeholders. Collisions are retried with new `{hex}` values.

**Design**:
- `get_or_create_session_branch()` in `utils.py`: Called by write tools. Creates branch on first invocation, returns cached branch name on subsequent calls.
- `expand_branch_pattern()`: Replaces placeholders. `{hex}` uses `secrets.token_hex()` for cryptographic randomness.
- `sanitize_user_for_branch()`: 8-rule regex pipeline ensuring git `check-ref-format` compliance. Handles emails (strips domain), special characters, git-forbidden sequences (`..`, `~`, `^`, `:`, `@{`, `\`).
- Collision retry: Up to `max_branch_retries` (configurable 1-20, default 5) attempts with fresh `{hex}`.
- Default branch protection: `assert_writable_branch()` blocks writes targeting the instance's default branch.

**Rationale**: Lazy creation avoids orphaned branches for read-only sessions (which are the majority). Pattern-based naming with user identity supports audit trail requirements. Collision retry with cryptographic randomness makes conflicts extremely unlikely but handles them gracefully.

**Alternatives considered**:
- Eager branch creation at session start (rejected: creates orphaned branches for read-only sessions, wasting Infrahub resources)
- Sequential branch numbering (rejected: requires querying existing branches, race-prone in concurrent environments)
- UUID-based branch names (rejected: not human-readable, harder to identify in Infrahub UI)

## R5: Config Validation at Boundary, Not Model

**Decision**: OIDC field validation happens at `load_config()` function level, not as a Pydantic `@field_validator` or `@model_validator`.

**Design**:
- `ServerConfig` is a frozen `BaseSettings` model with `env_prefix="INFRAHUB_MCP_"`, case-insensitive.
- `_validate_auth_requirements()` is a standalone function called by `load_config()`.
- It checks that all required OIDC fields (`config_url`, `client_id`, `base_url`) are present when `auth_mode=oidc`.

**Rationale**: Keeping OIDC validation at the `load_config()` boundary (not inside the model) allows unit tests to construct `ServerConfig(auth_mode="oidc")` without stubbing every OIDC field. The env-driven requirement is a deployment concern, not a model invariant. Frozen model ensures immutability after construction — config is only mutable at startup.

**Alternatives considered**:
- `@model_validator(mode="after")` (rejected: forces tests to provide all OIDC fields even when testing unrelated config)
- Mutable config with runtime updates (rejected: race conditions in async environment, harder to reason about)
- Separate config classes per auth mode (rejected: over-engineering for 4 modes, one frozen model is simpler)
