# Infrahub MCP Changelog

This is the changelog for the Infrahub MCP server.
All notable changes to this project will be documented in this file.

Issue tracking is located in [GitHub](https://github.com/opsmill/infrahub-mcp/issues).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This project uses [*towncrier*](https://towncrier.readthedocs.io/) and the changes for the upcoming release can be found in <https://github.com/opsmill/infrahub-mcp/tree/stable/changelog/>.

<!-- towncrier release notes start -->

## [Infrahub MCP - v1.3.0](https://github.com/opsmill/infrahub-mcp/tree/v1.3.0) - 2026-11-09

### Security

- The container image rejects certificates that chain through the compromised eMudhra intermediate CAs ([incident page](https://emudhra.we-have-a-problem.com/)). The build stage moves to uv 0.13.6 on Debian trixie. The runtime stage upgrades `ca-certificates`.

### Added

- Added a guide to deploying the MCP server on Kubernetes with the `infrahub-mcp` Helm chart, either standalone or as part of the `infrahub` chart.

### Changed

- Tool call errors now follow the MCP specification and FastMCP's own error mapping:

  - A call with invalid arguments returns a tool result with `isError: true` that carries the validation message, instead of a JSON-RPC `-32603 Internal error`.
  - In OIDC mode, a call that the token's scopes do not allow returns a tool result with `isError: true` that names the missing scopes, instead of a JSON-RPC `-32603 Internal error`.
  - A call to an unknown tool returns JSON-RPC `-32602`, as SEP-2164 requires, instead of `-32001`. In OIDC mode, the scope check rejects the call first and returns a tool result with `isError: true`. In read-only mode, the call returns JSON-RPC `-32601`.
  - When Infrahub is unreachable, not responding or rejects the credentials, a tool call now returns the message with the remediation hint, such as "Check that the instance is running", instead of the raw Infrahub SDK message.
  - The server's error-handling middleware logs a tool call error at `WARNING` level instead of `ERROR` level, because the error is a result the model acts on, not a server fault. FastMCP core and the structured logging middleware still log the error at `ERROR` level.

  ([#234](https://github.com/opsmill/infrahub-mcp/issues/234))

### Fixed

- In read-only mode, the server no longer lists or serves the `make_infra_change` prompt, which tells the agent to use write tools that read-only mode removes. With `auth_mode=oidc`, the prompt now also requires the write scope (`INFRAHUB_MCP_AUTH_SCOPES_WRITE`), like the write tools. ([#192](https://github.com/opsmill/infrahub-mcp/issues/192))
- OIDC mode now starts without `INFRAHUB_MCP_OIDC_CLIENT_SECRET` when the new `INFRAHUB_MCP_OIDC_JWT_SIGNING_KEY` is set, so the identity provider can register the MCP server as a public client. Before, the server stopped at startup with a FastMCP error in that setup. When neither variable is set, the server now stops with an error that names both. ([#215](https://github.com/opsmill/infrahub-mcp/issues/215))
- An error raised while a tool runs now returns a tool result with `isError: true` that carries the error message and any remediation hint, as the MCP specification recommends. This covers, for example, `get_nodes` with an unknown kind, a response over the size limit, a GraphQL mutation sent to `query_graphql`, and Infrahub SDK errors such as an unreachable Infrahub instance or a rejected API token. Since the upgrade to FastMCP 4 and MCP SDK 2, these errors reached the client as a JSON-RPC `-32603 Internal error`. Outside OIDC mode, unknown tools and calls to write tools on a read-only server still return JSON-RPC errors; in OIDC mode, the scope check rejects these calls first with a tool result with `isError: true`. Requests without passthrough credentials still return JSON-RPC errors. When the response of a write tool such as `node_upsert` or `mutate_graphql` is over the size limit, the error now says that the change was applied and that the tool must not be called again, instead of asking the client to narrow its filters and repeat the call. The server now requires FastMCP 4.1.0 or later, the first release that passes such an error on without replacing the exception that caused it. ([#218](https://github.com/opsmill/infrahub-mcp/issues/218))
- When retries are enabled with `INFRAHUB_MCP_RETRY_MAX_ATTEMPTS`, the server no longer retries a tool that is not annotated as idempotent or read-only, such as `node_upsert`, after a connection or timeout error. Before, every tool call was retried, so a write that reached Infrahub before the error could be applied more than once.
- Writes now reuse one session branch and `propose_changes` finds it when the client uses MCP protocol version 2026-07-28, which has no sessions. Previously every write created a new branch and `propose_changes` failed with "No session branch exists yet". Without an MCP session, the server now keeps one branch per authenticated caller identity (OIDC principal, passthrough token or Basic credentials), or one per server process when there is no authentication.

### Housekeeping

- After a final release is published, send the `infrahub-mcp-released` event to opsmill/infrahub-helm, which opens a pull request that moves the `infrahub-mcp` Helm chart to the new version.

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
