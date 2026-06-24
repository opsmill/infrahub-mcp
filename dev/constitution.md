<!--
Sync Impact Report
===================
Version change: 0.0.0 (unfilled template) → 1.0.0
Modified principles: N/A (initial constitution)
Added sections:
  - I. MCP Protocol Compliance
  - II. Infrahub SDK Integration
  - III. Branch-Safe by Default
  - IV. Type Safety & Explicit Contracts
  - V. Test Discipline
  - VI. Security & Input Boundaries
  - VII. Simplicity & Maintainability
  - Security & Performance Standards
  - Development Workflow & Quality Gates
  - Governance
Removed sections: None
Templates requiring updates:
  - .specify/templates/plan-template.md — Constitution Check placeholder
    now has concrete gates to reference ✅ (no file edit needed;
    plan-template instructs to derive gates from this file at plan time)
  - .specify/templates/spec-template.md — ✅ compatible (functional
    requirements and success criteria align with principles)
  - .specify/templates/tasks-template.md — ✅ compatible (phase structure
    supports test-first and security-hardening tasks)
Follow-up TODOs: None
-->

# Infrahub MCP Server Constitution

## Core Principles

### I. MCP Protocol Compliance

All tools, resources, and prompts MUST conform to the Model Context
Protocol specification. The server MUST behave as a well-formed MCP
endpoint that any standards-compliant client can consume.

- Tools MUST be registered through FastMCP's composition pattern
  (sub-applications mounted onto the main server).
- Tool responses MUST be deterministic and idempotent for read
  operations; write operations MUST be explicitly tagged (`"write"`).
- Resources MUST expose structured data via URI templates following
  MCP resource conventions.
- Prompts MUST provide clear, self-documenting templates that guide
  the AI assistant's interaction with Infrahub.
- Error responses MUST use MCP-standard error codes and messages;
  internal details MUST NOT leak to the client.

**Rationale:** The MCP standard exists so that any AI assistant can
connect to any MCP server without custom integration. Deviating from
the protocol breaks interoperability and forces client-side workarounds.

### II. Infrahub SDK Integration

All Infrahub operations MUST go through the `infrahub-sdk` client.
Direct HTTP calls to the Infrahub API are forbidden within tool and
resource implementations.

- The SDK client is created once during the application lifespan and
  shared via `AppContext`.
- GraphQL queries MUST use the SDK's query interface or the dedicated
  `graphql_query` / `mutate_graphql` tools, never raw `httpx` calls.
- Node operations (get, search, create, update, delete) MUST use the
  SDK's typed node interface.
- Schema introspection MUST use the SDK's schema API, cached via MCP
  resources where appropriate.

**Rationale:** The SDK handles authentication, retry logic, branch
awareness, and serialization. Bypassing it creates inconsistent
behavior, duplicates error handling, and breaks when the Infrahub API
evolves.

### III. Branch-Safe by Default

Write operations MUST be isolated to session branches. The default
branch MUST never be modified without explicit human approval via the
`propose_changes` workflow.

- Session branches are created automatically using the configured
  `branch_pattern` (supports `{date}`, `{hex}`, `{user}` placeholders).
- Read operations default to the `main` branch unless the caller
  specifies otherwise.
- The `ReadOnlyMiddleware` MUST block all tools tagged `"write"` when
  `read_only=true` is configured.
- Branch names MUST be validated against the allowed character set
  (alphanumeric, hyphens, underscores, dots, slashes).

**Rationale:** Infrastructure data is critical. Uncontrolled writes to
the default branch can propagate incorrect state to all consumers.
Branch isolation provides a review gate before changes take effect.

### IV. Type Safety & Explicit Contracts

All code MUST use the type system to enforce correctness at boundaries.

- **Python 3.13+** with full type annotations for all function
  parameters and return types.
- **Pydantic models** at configuration boundaries (`ServerConfig`)
  and API response shapes. Use `frozen=True` for immutable data.
- **MyPy clean** — no unresolved type errors. `# type: ignore` MUST
  include a specific error code and justification.
- Avoid `Any` at public interfaces. Use `str | None` (not
  `Optional[str]`). Prefer union types and type guards over casts.
- Configuration MUST be validated at startup via `pydantic-settings`;
  fail fast with clear error messages.

**Rationale:** An MCP server is a trust boundary between AI assistants
and infrastructure data. Type errors in tool responses or configuration
parsing can cause silent data corruption or security gaps.

### V. Test Discipline

Every feature MUST include tests at the appropriate level. Tests MUST
be written before or alongside implementation, not deferred.

- Every test is atomic, self-contained, and targets one behavior.
- Use **parametrization** for variants; avoid loops in tests.
- Imports at file top; no dynamic imports inside tests.
- Test files MUST mirror source structure (`tests/` parallels
  `src/infrahub_mcp/`).
- For MCP result objects in tests, use `# type: ignore[attr-defined]`
  instead of brittle type assertions.
- Prefer `pytest-asyncio` for async tool tests.
- Each feature requires corresponding tests (happy path + key edge
  cases).

**Rationale:** The MCP server mediates between AI assistants and
production infrastructure. Untested code paths risk exposing incorrect
data or allowing unintended mutations.

### VI. Security & Input Boundaries

Security MUST be enforced at system boundaries. Internal code may trust
validated data flowing through established interfaces.

- Credentials MUST be configured via environment variables
  (`INFRAHUB_API_TOKEN`, `INFRAHUB_ADDRESS`, etc.); never hardcoded.
- Secrets, API keys, and credentials MUST NOT appear in logs,
  exceptions, error responses, or repository files.
- Authentication mode (`none`, `oidc`, `token-passthrough`,
  `basic-passthrough`) MUST be validated at startup.
- OIDC configuration MUST be validated as a complete set — partial
  OIDC configuration MUST cause a startup failure.
- The ASGI middleware layer MUST handle credential passthrough
  (token or basic auth) via `ContextVar`, never global state.
- Tool inputs MUST be validated before passing to the Infrahub SDK.
- Error messages returned to clients MUST NOT expose internal
  implementation details, stack traces, or Infrahub API internals.

**Rationale:** The MCP server has access to an organization's entire
infrastructure data. A security breach could expose or corrupt network
topology, credentials, and configuration state.

### VII. Simplicity & Maintainability

Prefer the simplest solution that satisfies requirements. Complexity
MUST be justified.

- YAGNI: Do not implement features, abstractions, or configurability
  for hypothetical future requirements.
- Three similar lines of code are preferable to a premature abstraction.
- Follow established FastMCP patterns (middleware composition, sub-app
  mounting, lifespan context) rather than introducing alternatives.
- New dependencies MUST be justified; prefer stdlib or existing
  dependencies over new ones.
- Middleware MUST be composed via `configure_middleware()`, not
  scattered across modules.
- Generated code MUST be regenerated, never hand-edited.

**Rationale:** This is a focused server with a clear purpose. Unnecessary
complexity obscures the MCP protocol layer and makes it harder for
contributors to understand the request flow.

## Security & Performance Standards

### Security Requirements

- **Input validation:** Pydantic models at configuration boundaries.
  Tool parameter validation via FastMCP's built-in schema enforcement.
- **Authentication:** Four supported modes with strict validation:
  `none` (development), `oidc` (production), `token-passthrough`,
  `basic-passthrough` (delegated auth).
- **Credential isolation:** Per-request credentials via `ContextVar`,
  never stored in global state or logged.
- **Dependency management:** `uv` for Python packages. Dependency
  additions require review. Known vulnerability patches MUST be
  applied promptly.

### Performance Standards

- **Middleware efficiency:** The middleware stack (logging, timing,
  error handling, caching, rate limiting, audit) MUST be composed
  once at startup, not rebuilt per request.
- **Response caching:** Schema and list operations SHOULD use
  `ResponseCachingMiddleware` with configurable TTLs.
- **Rate limiting:** Token-bucket rate limiting MUST be configurable
  via `rate_limit_rps` and `rate_limit_burst`.
- **Response size control:** `ResponseLimitingMiddleware` MUST
  prevent oversized responses from consuming client context windows.
- **Observability:** OpenTelemetry tracing and Prometheus metrics
  MUST be available as opt-in features.

## Development Workflow & Quality Gates

### Code Quality Gates

All code MUST pass these gates before merge:

1. **Dependencies:** `uv sync` — lock file up to date.
2. **Formatting & Linting:** `uv run pre-commit run` — ruff format,
   ruff lint, mypy. Zero errors.
3. **Tests:** `uv run pytest` — all tests pass.
4. **Documentation:** `uv run rumdl check docs/docs/` for any
   documentation changes.

### Git Workflow

- Main branch: `stable` (production).
- Feature branches use the `feat/<name>` convention (e.g.,
  `feat/add-middleware`, `feat/analytics-reports`). Git worktrees
  flatten the slash to a hyphen locally (`feat-add-middleware`).
- Feature branches from `stable`, merged via PR.
- Agents MUST identify themselves in commits/PRs.
- Never force push to `stable`.
- Pre-commit hooks are required; don't amend commits to fix hook
  failures — make a follow-up commit.

### Documentation Requirements

- New user-facing features MUST be documented in `docs/docs/` (`.mdx`
  format, Diataxis framework).
- Architecture changes MUST update `dev/knowledge/`.
- New coding patterns MUST be captured in `dev/guidelines/`.
- Architectural decisions MUST be recorded in `dev/adr/`.

## Governance

This constitution is the authoritative reference for development
standards in the Infrahub MCP Server project. It supersedes informal
practices and ad-hoc decisions.

- **Compliance:** All pull requests and code reviews MUST verify
  adherence to these principles. Reviewers SHOULD reference specific
  principle numbers (e.g., "Principle III violation") when requesting
  changes.
- **Amendments:** Changes to this constitution require:
  1. A written proposal describing the change and rationale.
  2. Review and approval by a project maintainer.
  3. A migration plan if the change affects existing code.
  4. Version increment following semantic versioning (see below).
- **Versioning:**
  - MAJOR: Principle removal, redefinition, or backward-incompatible
    governance change.
  - MINOR: New principle or materially expanded guidance.
  - PATCH: Clarifications, wording fixes, non-semantic refinements.
- **Runtime guidance:** Coding standards in `dev/guidelines/` and
  architecture knowledge in `dev/knowledge/` provide detailed
  implementation guidance aligned with these principles.

**Version**: 1.0.0 | **Ratified**: 2026-04-21 | **Last Amended**: 2026-04-21
