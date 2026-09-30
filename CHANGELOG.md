# Infrahub MCP Changelog

This is the changelog for the Infrahub MCP server.
All notable changes to this project will be documented in this file.

Issue tracking is located in [GitHub](https://github.com/opsmill/infrahub-mcp/issues).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This project uses [*towncrier*](https://towncrier.readthedocs.io/) and the changes for the upcoming release can be found in <https://github.com/opsmill/infrahub-mcp/tree/stable/changelog/>.

<!-- towncrier release notes start -->

## [Infrahub MCP - v1.2.0](https://github.com/opsmill/infrahub-mcp/tree/v1.2.0) - 2026-09-30

### Added

- Load Infrahub credentials from a `.env` file in stdio / `.mcp.json` mode, so the API token can be kept out of a committed `.mcp.json`. Real environment variables take precedence, and `INFRAHUB_MCP_ENV_FILE` overrides the default `./.env` path. ([#147](https://github.com/opsmill/infrahub-mcp/issues/147))

### Fixed

- Require `fastmcp>=4.0.0` and `mcp>=2.0`, so installs that resolve fastmcp 3.x no longer fail with an `ImportError` on `MCPError`. ([#173](https://github.com/opsmill/infrahub-mcp/issues/173))
- Route version synchronization through a pull request instead of pushing generated files directly to `stable`, and make the untagged-version release guard explain how to prepare an authorized release.

### Housekeeping

- Adapt to MCP Python SDK 2.x and ruff 0.16.7: raise `MCPError(code=, message=)` instead of the removed `McpError(ErrorData(...))`, use the snake_case `ToolAnnotations` fields, and ignore the now code-less `pytest-fixture-autouse` ruff rule by name.
- Assemble release notes with towncrier instead of release-drafter: every pull request now carries a news fragment, and a reviewable release pull request publishes the assembled changelog as the GitHub Release body.
