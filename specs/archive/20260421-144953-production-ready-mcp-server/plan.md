# Implementation Plan: Production-Ready MCP Server (INFP-411)

**Branch**: `feat/add-middleware` | **Date**: 2026-04-21 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/20260421-144953-production-ready-mcp-server/spec.md`

**Note**: Retrospective plan — all features described here are already implemented. This plan exists to document the architectural decisions and enable ADR extraction via `/speckit.extract`.

## Summary

Build the middleware, authentication, read-only mode, and auto-branching layers that make the Infrahub MCP server production-ready. The implementation uses FastMCP's middleware composition pattern to create a 17-layer middleware stack composed once at startup, dual-layer authentication via ASGI credential extraction and MCP middleware enforcement, tag-based read-only filtering with defense-in-depth, and lazy session branch creation with collision retry.

## Technical Context

**Language/Version**: Python 3.13  
**Primary Dependencies**: FastMCP, Infrahub SDK, Pydantic 2, Starlette  
**Storage**: N/A (stateless — all state in Infrahub via SDK)  
**Testing**: pytest, pytest-asyncio  
**Target Platform**: Linux container (multi-arch: amd64/arm64), also runs locally via stdio  
**Project Type**: MCP server (library + web-service hybrid)  
**Performance Goals**: Middleware stack composed once at startup; per-request overhead < 5ms  
**Constraints**: Stateless — no local persistence; credentials via ContextVar only  
**Scale/Scope**: Single-server deployment, concurrent async requests via FastMCP/Starlette

## Constitution Check

*GATE: All gates pass — implementation verified against constitution principles.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | MCP Protocol Compliance | PASS | All tools registered via FastMCP sub-app mounting; error responses use MCP-standard codes |
| II | Infrahub SDK Integration | PASS | All Infrahub operations go through `infrahub-sdk`; no direct HTTP calls |
| III | Branch-Safe by Default | PASS | Write ops isolated to session branches; default branch blocked by `assert_writable_branch()` |
| IV | Type Safety & Explicit Contracts | PASS | Full type annotations; `ServerConfig` is frozen Pydantic model; MyPy clean |
| V | Test Discipline | PASS | Tests for each middleware, auth mode, read-only filtering, and branch creation |
| VI | Security & Input Boundaries | PASS | Credentials via env vars and ContextVar; never logged; OIDC validated at startup |
| VII | Simplicity & Maintainability | PASS | Single `configure_middleware()` entry point; follows FastMCP patterns throughout |

## Project Structure

### Documentation (this feature)

```text
specs/20260421-144953-production-ready-mcp-server/
├── plan.md              # This file
├── spec.md              # Feature specification (INFP-411)
├── research.md          # Architectural decision research (5 entries)
├── data-model.md        # Entity documentation
└── checklists/
    └── requirements.md  # Requirements checklist
```

### Source Code (repository root)

```text
src/infrahub_mcp/
├── middleware.py         # Full 17-layer middleware stack + configure_middleware()
├── config.py            # ServerConfig (pydantic-settings, frozen, env_prefix)
├── auth.py              # OIDC provider factory, identity helpers
├── server.py            # FastMCP server construction, ASGI app, sub-app mounting
├── utils.py             # Session branch creation, expand_branch_pattern, sanitize
├── schema.py            # Schema utilities
├── constants.py         # Shared constants
├── tools/               # MCP tool implementations (write tools tagged "write")
├── resources/           # MCP resources (branches, schema)
├── prompts/             # MCP prompt templates
└── auth/                # Auth sub-modules

tests/
├── test_middleware.py   # Middleware stack tests
├── test_config.py       # Configuration validation tests
├── test_auth.py         # Authentication mode tests
├── test_utils.py        # Branch creation, sanitization tests
└── ...
```

**Structure Decision**: Single-package layout matching existing FastMCP server conventions. Middleware is centralized in one file (`middleware.py`) per Constitution Principle VII — composed via `configure_middleware()`, not scattered across modules.

## Architectural Decisions (ADR Candidates)

These are the key decisions documented in [research.md](research.md) that should be extracted as formal ADRs:

| # | Decision | research.md Ref | ADR Priority |
|---|----------|----------------|-------------|
| 1 | 17-layer middleware stack ordered outermost→innermost, composed once at startup | R1 | High — defines the request processing architecture |
| 2 | Dual-layer auth: ASGI extracts credentials, MCP middleware enforces | R2 | High — security architecture |
| 3 | Tag-based read-only with defense-in-depth (hide + reject + fail-closed allowlist) | R3 | Medium — security pattern |
| 4 | Lazy session branch creation with collision retry | R4 | Medium — write safety pattern |
| 5 | Config validation at `load_config()` boundary, not model validators | R5 | Low — testability pattern |

## Implementation Phases (Retrospective)

### Phase 1: Configuration & Core Infrastructure

- `ServerConfig` via pydantic-settings with `INFRAHUB_MCP_*` prefix
- Frozen model (immutable after construction)
- `AppContext` for lifespan dependency injection
- `load_config()` with OIDC field validation at boundary

### Phase 2: Middleware Stack

- `configure_middleware()` composing 17 layers based on config
- Observability layers: RequestId, Metrics, OTelTracing, StructuredLogging, DetailedTiming
- Resilience layers: ErrorHandling, InfrahubConnection, Retry, RateLimiting
- Functional layers: ResponseCaching, DereferenceRefs, Ping, ResponseLimiting
- Security layers: Auth, TokenPassthrough, ReadOnly, Audit

### Phase 3: Authentication

- `_CredentialsPassthroughASGI` for HTTP credential extraction
- `TokenPassthroughMiddleware` for fail-closed enforcement
- `AuthMiddleware` for OIDC scope enforcement
- `OIDCProxy` integration from fastmcp for OAuth 2.0 flow
- ContextVar isolation for per-request credentials

### Phase 4: Read-Only Mode & Branch Safety

- Tag-based write tool filtering via `restrict_tag()`
- Three-layer defense: hide from listing + reject calls + fail-closed allowlist
- Lazy branch creation via `get_or_create_session_branch()`
- `expand_branch_pattern()` with `{date}`, `{hex}`, `{user}` placeholders
- `sanitize_user_for_branch()` with 8-rule regex pipeline
- `assert_writable_branch()` blocking default branch writes

## Complexity Tracking

No constitution violations. All features follow established FastMCP patterns.

## Next Steps

- Run `/speckit.extract` to generate formal ADRs from research.md entries
- Document deployment configuration in `docs/docs/`
- Container image and Helm chart integration (tracked separately)
