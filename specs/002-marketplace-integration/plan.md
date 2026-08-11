# Implementation Plan: Infrahub Marketplace integration for the MCP server

**Branch**: `atg-/marketplace-integration` | **Date**: 2026-07-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/002-marketplace-integration/spec.md`

## Summary

Add a marketplace-aware capability to the MCP server: agents can **search** the public Infrahub Marketplace catalog, **read** a schema's or collection's metadata and YAML (read-only, anonymous), and — when enabled and not read-only — **install** a chosen schema into the connected Infrahub on a session branch for human approval.

Technical approach: a net-new async `MarketplaceClient` service (`src/infrahub_mcp/marketplace.py`) over the marketplace's public `/api/v1` API, mirroring the URL scheme and schema-vs-collection auto-detect of `infrahub_sdk.ctl.marketplace`. A new `tools/marketplace.py` exposes three `readOnlyHint` read tools plus a `"write"`-tagged `marketplace_install` that loads YAML through the SDK's `client.schema.load(...)` onto the session branch. Two `ServerConfig` fields gate it (`marketplace_enabled`, `marketplace_url`); mounting follows the existing `if not read_only: mcp.mount(write_mcp)` idiom. No new dependency — `httpx` ships with the SDK.

## Technical Context

**Language/Version**: Python 3.13
**Primary Dependencies**: FastMCP, `infrahub-sdk` (client + `ctl.marketplace` as URL/semantics reference), `httpx` (already transitive via SDK), Pydantic 2, Starlette
**Storage**: None — marketplace state is external; install writes go through the SDK to Infrahub
**Testing**: pytest, pytest-asyncio; httpx mocked for the client; testcontainers Infrahub for the install E2E (builds on `001-infrahub-testcontainers`)
**Target Platform**: Linux server (ASGI / MCP endpoint)
**Project Type**: Single project — MCP server library
**Performance Goals**: Discovery interactive (well under a few seconds per call); no new per-request middleware cost
**Constraints**: No Infrahub credentials on marketplace requests; honour SDK proxy/TLS; errors sanitised (no internal detail); install branch-isolated
**Scale/Scope**: 3 read tools + 1 write tool + 1 service module + 2 config fields; ~1 new source module pair plus tests

**Open unknown (see research.md)**: the marketplace **search** endpoint is not exercised by `ctl.marketplace` (which only downloads by known ref). Its exact path/params are assumed and must be confirmed against the live API before implementing FR-001.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| I. MCP Protocol Compliance | Read tools `readOnlyHint`; install tagged `"write"`; MCP-standard errors, no internal leak | PASS — tools follow FastMCP sub-app pattern; errors via `_log_and_raise_error` |
| II. Infrahub SDK Integration | No raw HTTP **to Infrahub**; install loads via SDK | PASS — marketplace HTTP is to a *separate external service* (explicitly allowed by spec/PRD); the Infrahub-side load uses `client.schema.load` |
| III. Branch-Safe by Default | Install session-branch isolated; blocked in read-only | PASS — `get_or_create_session_branch`; write-tagged so `ReadOnlyMiddleware` blocks it; also not mounted when `read_only` |
| IV. Type Safety & Contracts | Typed models, config validated at startup, mypy clean | PASS — `MarketplaceClient` returns typed models; `marketplace_url`/`marketplace_enabled` validated in `ServerConfig` |
| V. Test Discipline | Unit (mocked httpx) + contract (gating) + E2E (install) | PASS — planned below |
| VI. Security & Input Boundaries | No creds on marketplace calls; refs validated; errors sanitised | PASS — dedicated client carries no Infrahub auth; ref parsed/validated before use |
| VII. Simplicity | No new dep; reuse existing idioms | PASS — mirrors `ctl.marketplace` semantics and the write-tool mount/gating pattern |

**Governance "Ask First" (AGENTS.md)**: this is an API/public-interface change **and** a new external-service call path + new write tool (authorization surface). Requires maintainer sign-off — flagged in spec Governance Gates.

No violations → Complexity Tracking not needed.

## Project Structure

### Documentation (this feature)

```text
specs/002-marketplace-integration/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (MCP tool contracts)
│   └── mcp-tools.md
└── checklists/
    └── requirements.md   # from /speckit-specify
```

### Source Code (repository root)

```text
src/infrahub_mcp/
├── marketplace.py            # NEW — MarketplaceClient service + typed models + error categories
├── tools/
│   └── marketplace.py        # NEW — read tools (mcp) + write install (install_mcp)
├── config.py                 # EXTEND — marketplace_enabled (default True), marketplace_url
└── server.py                 # EXTEND — import + gated mount of marketplace sub-apps

tests/
├── unit/
│   ├── test_marketplace_client.py   # NEW — mocked httpx: refs, auto-detect, gzip, pagination, error mapping
│   └── test_marketplace_tools.py    # NEW — read-only guard, session-branch routing, validation-failure, config gating
└── integration/
    └── test_marketplace_install.py  # NEW — E2E search→get_schema→install on session branch (testcontainers)
```

**Structure Decision**: Single-project layout, mirroring the existing `tools/schema.py` → `schema.py` split (thin tool layer over a service module) and the `tools/write.py` session-branch + write-tag conventions. `tools/marketplace.py` defines two FastMCP instances — `mcp` (reads) and `install_mcp` (write) — so `server.py` can mount them under the existing config gating idiom.

## Complexity Tracking

No constitution violations — section intentionally empty.
