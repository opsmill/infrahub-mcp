# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- OAuth/OIDC authentication mode with per-request token verification.
- Token-passthrough authentication mode: clients can forward an Infrahub API token via the `Authorization` header.
- Username/password (Basic) request passthrough mode.
- 17-layer middleware stack: structured logging, timing, error handling, audit, read-only enforcement, rate limiting, retry with exponential backoff, response caching, OpenTelemetry tracing, Prometheus metrics.
- `/health` endpoint for container orchestration probes.
- `/metrics` endpoint exposing JSON or Prometheus text format.
- `infrahub_app` FastMCPApp: `explore` and `overview` tools with auto-detect panels, charts, and ER diagrams.
- Schema query depth parameter (`INFRAHUB_MCP_MAX_QUERY_DEPTH`) with cycle detection in nested peer expansion.
- Configurable protected branches list (`INFRAHUB_MCP_BRANCH_PROTECTED`) — writes to `main` are rejected by default.
- Multi-arch Docker image publication to `registry.opsmill.io/opsmill/infrahub-mcp-server` for `linux/amd64` and `linux/arm64`.
- Documentation for authentication modes with Mermaid flow diagrams.

### Changed

- Configuration loading rewritten on top of `pydantic-settings` with grouped per-subsystem `BaseSettings` classes. All existing `INFRAHUB_MCP_*` environment variables remain compatible.
- `AUTH_SCOPES_WRITE` default is now `"write"` (previously resolved via a runtime fallback).
- Replaced root `README.md` and `CHANGELOG.md`, which carried upstream template content.

### Fixed

- `ReadOnlyMiddleware` now fails closed when the operation type cannot be determined.
- Passthrough credentials are reset on the way out of every request; a fresh Infrahub client is created per call.
- RFC 6749 JSON `404` is returned for well-known OAuth/OIDC discovery probes when OIDC is disabled, so clients do not trip on plain-text responses.
- Infrahub SDK connection errors are caught inside middleware and surfaced as clean MCP errors.

## [1.0.2] - 2026-04-10

### Fixed

- CI: prevent shell injection in the auto-bump guard step.
- CI: extract the `mcp-discovery` release binary with `--strip-components=1`.

### Changed

- Added the CI/CD versioning and release process.

## [1.0.1] - 2026-04-07

### Added

- `feat: enrich MCP error messages with schema discovery hints` (#54).

### Changed

- Dependency upgrades: `fastmcp` 3.2.0, `aiohttp` 3.13.4, `pygments` 2.20.0, `cryptography` 46.0.7, and several docs dependency bumps.

### Fixed

- Resolved Dependabot security alerts (#40).

## [1.0.0] - 2026-03-26

### Added

- Branch-per-session write workflow: writes land on an auto-created session branch, never the default branch.
- Schema and branches exposed as MCP resources alongside the existing tools.
- `query_graphql` tool now supports a `branch` parameter.
- TOON encoding for structured arrays, reducing token usage by 33–45%.
- Integration tests migrated from the OpenAI Agents SDK to the Anthropic SDK.

### Changed

- Tool surface consolidated to a 6-tool design with schema/branch as resources.

## [0.1.1] - 2025-09-26

Initial public release of the Infrahub MCP Server.

[Unreleased]: https://github.com/opsmill/infrahub-mcp/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/opsmill/infrahub-mcp/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/opsmill/infrahub-mcp/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/opsmill/infrahub-mcp/compare/v0.1.1...v1.0.0
[0.1.1]: https://github.com/opsmill/infrahub-mcp/releases/tag/v0.1.1
