# Infrahub MCP Changelog

This is the changelog for the Infrahub MCP server.
All notable changes to this project will be documented in this file.

Issue tracking is located in [GitHub](https://github.com/opsmill/infrahub-mcp/issues).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This project uses [*towncrier*](https://towncrier.readthedocs.io/) and the changes for the upcoming release can be found in <https://github.com/opsmill/infrahub-mcp/tree/stable/changelog/>.

<!-- towncrier release notes start -->

## [Infrahub MCP - v1.2.1](https://github.com/opsmill/infrahub-mcp/tree/v1.2.1) - 2026-10-27

### Security

- Upgraded authlib from 1.7.2 to 1.9.1 and dnspython from 2.8.0 to 2.9.0 in the locked dependencies used by the container image, and require `authlib>=1.9.1` so pip and uvx installs cannot resolve a release affected by GHSA-6v38-4h7w-rj9h, GHSA-7vr2-2fgp-9w7p or GHSA-8m4g-j4wp-wgcg. The server does not call the affected authlib or dnspython code paths; the upgrade removes the vulnerable versions from the image.

### Changed

- An `.env` line that leaves the API token blank with an inline comment, such as `INFRAHUB_API_TOKEN= # fill me in`, now sets an empty token instead of the comment text. With no other credentials, startup reports that authentication is required instead of sending the comment to Infrahub as the token; with `INFRAHUB_USERNAME` and `INFRAHUB_PASSWORD` set, the server logs in with them instead of stopping with "Conflicting credentials". This follows python-dotenv 1.2.4, which is now the minimum supported version.
- Container images now follow the Infrahub tagging scheme: `latest` only moves when the release is GitHub's latest release, and each release is also tagged `stable` (or `preview` for pre-releases) and, for full releases, `vX.Y`.

### Fixed

- Publish GitHub Releases from the curated release-notes page when one exists, and avoid rerunning the general CI workflow after a reviewed pull request is merged.

### Housekeeping

- Updated AnyIO from 4.14.0 to 4.14.2 to include upstream fixes for cancellation, concurrency limits, subprocess handling, and TLS hostname validation. ([#166](https://github.com/opsmill/infrahub-mcp/issues/166))
- Exercise stdio and streamable HTTP round trips, concurrent requests, cancellation cleanup, and server shutdown in the default test suite to catch transport regressions from dependency updates.
- Exercise the GraphQL read and write tools with real parser results to guard mutation rejection, syntax errors, and branch routing during dependency upgrades.
- Regenerate MCP capabilities for FastMCP 4.1.2 and check capabilities freshness when dependencies change.
- Standardized release bump labels and now reject pull requests with missing or conflicting release intent.
- Test SDK default branch selection during server startup from Git repositories, linked worktrees, and deployments with an explicitly configured branch.
- The Update Infrahub Version workflow now writes `infrahub-testcontainers` with a lower and an upper bound (for example `>=1.11.3,<2`) instead of rewriting it as an exact `==` pin on every bump, while still locking exactly the requested release.
- Updated application lifespan typing for compatibility with the upgraded Ruff and ty releases.
- Upgraded the documentation site dependencies to clear the open Dependabot alerts for docs/pnpm-lock.yaml, pinned tinypool, Mermaid and the React type definitions through pnpm overrides, and added the docs site to the Dependabot version-update configuration.

## [Infrahub MCP - v1.2.0](https://github.com/opsmill/infrahub-mcp/tree/v1.2.0) - 2026-09-30

### Added

- Load Infrahub credentials from a `.env` file in stdio / `.mcp.json` mode, so the API token can be kept out of a committed `.mcp.json`. Real environment variables take precedence, and `INFRAHUB_MCP_ENV_FILE` overrides the default `./.env` path. ([#147](https://github.com/opsmill/infrahub-mcp/issues/147))

### Fixed

- Require `fastmcp>=4.0.0` and `mcp>=2.0`, so installs that resolve fastmcp 3.x no longer fail with an `ImportError` on `MCPError`. ([#173](https://github.com/opsmill/infrahub-mcp/issues/173))
- Route version synchronization through a pull request instead of pushing generated files directly to `stable`, and make the untagged-version release guard explain how to prepare an authorized release.

### Housekeeping

- Adapt to MCP Python SDK 2.x and ruff 0.16.7: raise `MCPError(code=, message=)` instead of the removed `McpError(ErrorData(...))`, use the snake_case `ToolAnnotations` fields, and ignore the now code-less `pytest-fixture-autouse` ruff rule by name.
- Assemble release notes with towncrier instead of release-drafter: every pull request now carries a news fragment, and a reviewable release pull request publishes the assembled changelog as the GitHub Release body.
