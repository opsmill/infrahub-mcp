# 6. Configuration validation at boundary, not model

**Status:** Accepted
**Date:** 2026-04-21
**Author:** @bkohler

## Context

`ServerConfig` is a frozen Pydantic `BaseSettings` model loaded from `INFRAHUB_MCP_*` environment variables. When `auth_mode=oidc`, three additional fields are required: `oidc_config_url`, `oidc_client_id`, and `oidc_base_url`. The question was where to enforce this cross-field validation.

Pydantic offers `@model_validator(mode="after")` for cross-field checks, but this forces every test that constructs a `ServerConfig` to provide all OIDC fields — even tests for unrelated configuration like rate limiting or branch patterns.

## Decision

OIDC field validation happens at the `load_config()` function level, not as a Pydantic model validator.

- `ServerConfig` is a frozen `BaseSettings` model with `env_prefix="INFRAHUB_MCP_"`, case-insensitive
- `_validate_auth_requirements()` is a standalone function called by `load_config()`
- It checks that all required OIDC fields are present when `auth_mode=oidc` and raises a clear error listing missing fields with documentation references
- The model itself remains a simple data container with per-field validators only (for example, `branch_pattern` placeholder validation, `log_level` enum check)

## Consequences

### Positive

- Unit tests can construct `ServerConfig(auth_mode="oidc")` without stubbing every OIDC field — only tests exercising the OIDC validation path need the full set
- Clear separation: the model defines shape and field-level constraints, the loader enforces deployment-level requirements
- Frozen model guarantees immutability after construction — no runtime configuration mutations

### Negative

- Validation is split across two locations: field validators in the model, cross-field checks in the loader
- A developer constructing `ServerConfig` directly (not via `load_config()`) could create an invalid OIDC configuration — but this only happens in tests, which is the desired behavior

### Neutral

- The env-driven OIDC requirement is a deployment concern, not a model invariant — this framing matches the boundary principle (Constitution VI: validate at system boundaries)

## Alternatives Considered

### `@model_validator(mode="after")`

Validate OIDC fields inside the Pydantic model. Rejected: forces every test to provide all OIDC fields when constructing `ServerConfig`, even when testing unrelated configuration. This creates test friction without adding safety (production always goes through `load_config()`).

### Mutable configuration with runtime updates

Allow configuration to be modified after startup. Rejected: race conditions in async environments, harder to reason about which values are active during a request. Frozen model eliminates an entire class of bugs.

### Separate configuration classes per auth mode

Create `OidcConfig`, `TokenPassthroughConfig`, etc. Rejected: over-engineering for four modes. One frozen model with optional fields is simpler and sufficient.
