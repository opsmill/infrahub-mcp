# Phase 0 Research: Marketplace integration

Grounded in the codebase (`tools/write.py`, `tools/schema.py`, `server.py`, `config.py`) and `infrahub_sdk.ctl.marketplace` (the reference implementation for URL scheme and semantics).

## Decision 1 — Marketplace client is net-new, not an SDK import

- **Decision**: Build `MarketplaceClient` in `src/infrahub_mcp/marketplace.py` as a thin async `httpx` client over `/api/v1`, mirroring `infrahub_sdk.ctl.marketplace`'s URLs and semantics.
- **Rationale**: The SDK exposes marketplace access only as a `typer` CLI (`ctl/marketplace.py`) that prints to a console and raises `typer.Exit` — nothing importable. The URL scheme and auto-detect logic are, however, well-defined there and can be reproduced faithfully. `httpx` is already a transitive dependency (no new dep).
- **Alternatives rejected**: (a) shelling out to `infrahubctl marketplace` — brittle, couples us to CLI output formatting; (b) waiting for an SDK client — none exists.

## Decision 2 — URL scheme (from `ctl/marketplace.py`)

- Schema (latest): `GET {base}/api/v1/schemas/{ns}/{name}/download`
- Schema (pinned): `GET {base}/api/v1/schemas/{ns}/{name}/versions/{version}/download`
- Collection: `GET {base}/api/v1/collections/{ns}/{name}`
- **Auto-detect**: probe schema + collection URLs in parallel (`asyncio.gather`, `return_exceptions=True`). Both 200 → **schema wins**, surface the ambiguity (FR-011). Neither 200 but a 5xx/transport error present → "cannot reach". Otherwise → "not found".
- `base_url` is `.rstrip("/")`-normalised, matching the CLI.

## Decision 3 — Search / list / detail endpoints (RESOLVED via SDK PR #1128)

- **Decision**: Implement `marketplace_search` (and the metadata half of `get_schema`/`get_collection`) against the endpoints confirmed by `opsmill/infrahub-sdk-python` PR #1128 (`feat(ctl): add marketplace browsing commands`):
  - **List/search**: `GET {base}/api/v1/schemas` or `{base}/api/v1/collections`, query params `search=<term>`, `limit=<N>`, `cursor=<end_cursor>`.
  - **Detail**: `GET {base}/api/v1/{schemas|collections}/{ns}/{name}` — returns versions/members + dependencies.
  - **Pagination**: cursor-based. Response has `page_info.{has_next_page, end_cursor}`. Fetch all pages by default; stop when `has_next_page` is false **or** no cursor is returned (guard against a claimed-but-missing cursor). A `limit` requests a single page.
  - **Item fields** (raw dict, **confirmed live** against marketplace.infrahub.app, 2026-07-03): `namespace`, `name`, `display_name`, `description`, `download_count`, `author: {username, ...}`, `tags: [{id, name}]`, `latest_version: {semver, download_url, ...}`; collections add `schema_count`. Envelope: `{items, page_info: {has_next_page, end_cursor}, total_count}`. **Caught in testing**: these differ from PR #1128's *test-fixture* names (`display`, `downloads`, string `tags`); `_catalog_entry` maps tolerantly to both, keyed on the live shape.
  - **Error taxonomy**: 4xx → not-found/invalid-ref; 5xx/transport (incl. invalid JSON body) → `unreachable`. Matches Decision 4.
- **Rationale**: #1128 hits the marketplace's *existing* list/detail REST endpoints (its PR body states "no new marketplace API endpoints"), so this is the authoritative public contract. It supersedes the earlier assumption — no live probe needed.
- **Caveat**: #1128 is CLI-only (typer, raw dicts, no importable client) and, at time of writing, **open/unmerged**. It is our **reference to mirror**, not a dependency to import (same relationship as the existing `get`/download code — see Decision 1). Re-verify the endpoint shape if #1128's contract changes before merge.
- **Residual unknown**: #1128 exposes only `search=` (free-text). Server-side `tag`/`namespace` filters (FR-001) are **not** confirmed as query params. Fallback: fold namespace/tag into the `search` term or filter client-side on the returned `namespace`/`tags` fields until a dedicated param is confirmed. Minor — does not block the story.
- **Alternatives rejected**: scraping the marketplace web UI — fragile, not a contract.

## Decision 4 — Error categories

- **Decision**: A small enum of categories mapped to MCP errors via the existing `_log_and_raise_error(ctx, error=..., remediation=...)` helper:
  - `invalid-ref` — reference not `namespace/name` (parsed before any HTTP).
  - `not-found` — 404 on both probes / unknown ref.
  - `no-such-version` — 404 on a *versioned* URL when the schema is confirmed to exist (distinct from generic not-found — matches CLI).
  - `unreachable` — transport error or 5xx (distinct from not-found — matches CLI `_ErrorClass.NETWORK`).
  - `too-large` — 413 on a collection bundle; relay a clear "too large" message.
- **Rationale**: SC-004 requires the operator to tell ref vs content vs service apart in one message; mirrors the CLI's `_ErrorClass` split. Sanitised strings only — no stack traces, no internal detail (Principle VI).

## Decision 5 — Credential isolation, proxy/TLS

- **Decision**: `MarketplaceClient` builds its own `httpx.AsyncClient` carrying **no Infrahub auth headers**, inheriting the SDK config's proxy/TLS exactly as `ctl.marketplace._make_http_client` does (`proxy`/`proxy_mounts`, `verify=sdk_cfg.tls_context`, `follow_redirects=True`).
- **Rationale**: FR-009 / Principle VI — reaching an external service must not leak internal secrets, but must still work behind a corporate proxy / custom CA.

## Decision 6 — Content decoding (gzip)

- **Decision**: Rely on httpx's automatic `Content-Encoding` decompression for transfer-level gzip; use `resp.text` for YAML. If the marketplace returns gzip **as the payload body** (not transfer encoding), decompress with stdlib `gzip` before parsing. Read `x-schema-version` response header for the resolved version (as the CLI does).
- **Rationale**: Avoid guessing — the CLI reads `resp.text` directly, implying transfer-level encoding handled by httpx. Confirm during implementation with one real response; add stdlib `gzip` only if needed (YAGNI).

## Decision 7 — Install path (Infrahub-side write)

- **Decision**: `marketplace_install` resolves the ref, downloads the YAML, parses it to the `list[dict]` shape, calls `get_or_create_session_branch(ctx)` then `client.schema.load(schemas=[...], branch=session_branch)`. Response reports the session branch and what was applied. Validation failures from `schema.load` surface as the SDK's error on the branch; default branch untouched.
- **Rationale**: Reuses the exact session-branch conventions from `tools/write.py` (`get_or_create_session_branch`, session-branch routing) and the SDK's existing schema-load path (Principle II — Infrahub writes go through the SDK).
- **Alternatives rejected**: writing schema via raw GraphQL — forbidden by Principle II and `_BLOCKED_MUTATIONS` already blocks schema mutations.

## Decision 8 — Config gating & tool mounting

- **Decision**: Add `marketplace_enabled: bool = True` (FR-007 — default ON per clarification) and `marketplace_url: str = "https://marketplace.infrahub.app"` (FR-008) to `ServerConfig`, validated at startup. In `server.py`:
  ```python
  if _config.marketplace_enabled:
      mcp.mount(marketplace_mcp)              # read tools
      if not _config.read_only:
          mcp.mount(marketplace_install_mcp)  # write install
  ```
- **Rationale**: Mirrors the existing `if not _config.read_only: mcp.mount(write_mcp)` idiom exactly (Principle VII). `ReadOnlyMiddleware` remains the runtime backstop for the write-tagged install (belt-and-suspenders, FR-006). When disabled, tools are simply never mounted → SC-003 (no capability, no external call).
- **URL validation**: `marketplace_url` validated as a well-formed http(s) URL at startup (Principle IV), `.rstrip("/")`-normalised like the CLI.
