# Implementation Plan: Graph Traversal Tools + Single-Level Schema Expansion

**Branch**: `feat/schema-query-depth` (speckit `002-traversal-tools`) | **Date**: 2026-06-24 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/002-traversal-tools/spec.md`

## Summary

Add two read-only MCP tools — `find_paths` (shortest path(s) between two objects) and `find_reachable` (objects of given kinds reachable from a source) — that wrap the Infrahub 1.10 graph-traversal API exposed by infrahub-sdk ≥ 1.22 (`traverse_paths`, `reachable_nodes`). In the same change, collapse the prior recursive schema-depth expansion to a single non-recursive level controlled by a boolean setting. Traversal logic lives in a testable core module with thin tool wrappers, mirroring the existing `schema.py` ↔ `tools/schema.py` split.

## Technical Context

**Language/Version**: Python 3.13
**Primary Dependencies**: FastMCP, infrahub-sdk ≥ 1.22.0, Pydantic 2, TOON
**Storage**: N/A (stateless MCP server over the Infrahub API)
**Testing**: pytest + pytest-asyncio; new unit tests mock the SDK and run without a live server
**Target Platform**: Linux/macOS server process (MCP over stdio/HTTP)
**Project Type**: Single project — Python library/MCP server (`src/infrahub_mcp/`)
**Performance Goals**: Traversal is server-side; tool overhead is one resolution lookup per non-UUID reference plus one traversal call. Responses kept compact (TOON, minimal per-hop fields)
**Constraints**: Requires Infrahub server ≥ 1.10; unsupported servers handled with a clear error. Read-only — no mutations
**Scale/Scope**: 2 new tools, 1 new core module, 1 schema refactor, 1 config field; ~3 new/changed test files

## Constitution Check

*GATE: Must pass before implementation.* Checked against `dev/constitution.md` / `AGENTS.md` boundaries.

- **Use the SDK for all Infrahub access** — PASS. All traversal/resolution goes through `InfrahubClient` (`traverse_paths`, `reachable_nodes`, `get`); no raw HTTP.
- **Write tools tagged `write`** — N/A / PASS. Both new tools are read-only (`readOnlyHint=True`, tags `{"traversal","retrieve"}`), so they must NOT carry the `write` tag.
- **Validate configuration at startup via `ServerConfig`** — PASS. The new `schema_expand_peers` field lives on the existing `ServerConfig`, validated at construction.
- **Per-request state via context, no global mutable state** — PASS. Client/config obtained via `get_client(ctx)` / `get_config(ctx)`.
- **No `Any` in public interfaces without justification** — PASS. Public functions are fully typed; SDK result models are typed via `infrahub_sdk.graph_traversal`.
- **Ask First — API/schema contract changes** — Honored. The schema-tool param change (`depth`→`expand`) and config rename were approved during design; both are pre-release (unmerged), so non-breaking.

No violations. Complexity Tracking table omitted (nothing to justify).

## Project Structure

### Documentation (this feature)

```text
specs/002-traversal-tools/
├── spec.md              # WHAT/WHY (specify phase)
├── plan.md              # This file
├── research.md          # Decisions & rationale
├── data-model.md        # Entities (traversal result shapes, peer schema)
├── quickstart.md        # Usage flows
├── contracts/
│   └── tools.md         # Tool I/O contracts + get_schema change
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Task breakdown (tasks phase)
```

### Source Code (repository root)

```text
src/infrahub_mcp/
├── config.py                 # MODIFY: add boolean schema_expand_peers (replaces max_query_depth)
├── schema.py                 # MODIFY: single-level get_schema_detail; delete recursion helpers
├── traversal.py              # CREATE: core logic — resolve_node_ref, shaping, run_find_paths/run_find_reachable
├── server.py                 # MODIFY: mount traversal tools; update description
├── tools/
│   ├── schema.py             # MODIFY: get_schema depth→expand
│   └── traversal.py          # CREATE: find_paths / find_reachable tool wrappers
└── resources/
    └── schema.py             # MODIFY: use config.schema_expand_peers

tests/unit/
├── test_traversal.py         # CREATE: resolution, shaping, orchestration, tool error translation
├── test_schema_expand.py     # CREATE: single-level expansion (replaces test_schema_depth.py)
└── test_config.py            # MODIFY: schema_expand_peers toggle

docs/docs/references/
└── methods.mdx               # MODIFY: document find_paths/find_reachable + get_schema expand

pyproject.toml                # MODIFY: infrahub-sdk floor → >=1.22.0
```

**Structure Decision**: Single-project Python MCP server. The traversal feature follows the established core/tool split (`schema.py` ↔ `tools/schema.py`) so the logic is unit-testable without a live server and the tool wrapper stays thin.

> The exhaustive, code-complete task breakdown (every step with full code and exact commands) lives in `docs/superpowers/plans/2026-06-24-traversal-tools.md`. `tasks.md` (next phase) is the speckit-format index over those same tasks.
