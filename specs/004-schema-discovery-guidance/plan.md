# Implementation Plan: Schema-Discovery Guidance in Every MCP Client

**Branch**: `feat/schema-discovery-guidance` (speckit `004-schema-discovery-guidance`) | **Date**: 2026-10-12 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/004-schema-discovery-guidance/spec.md`

## Summary

Agents that connect without the `infrahub_agent` prompt guess kind names and GraphQL filter syntax, because the schema-first rule exists only in that prompt ([issue 191](https://github.com/opsmill/infrahub-mcp/issues/191)). This plan moves the rule into the two channels that reach the model without a user action:

- server instructions, built from one function that also feeds the `infrahub_agent` prompt;
- tool and parameter descriptions, which name `get_schema` directly instead of "the resource, or the tool if your client cannot read resources".

The plan also makes the schema resources accept a branch, and adds a setting that is off by default and exposes every resource through two general-purpose tools for clients that pass only tools. `get_schema` stays unchanged, and prompts are not exposed as tools. Decisions and sources are in [research.md](./research.md).

## Technical Context

**Language/Version**: Python 3.13
**Primary Dependencies**: FastMCP 4.0.10 (`ResourcesAsTools` transform, RFC 6570 query templates, `instructions=`), MCP SDK 2.2.0, infrahub-sdk, pydantic-settings. No new dependency.
**Storage**: N/A
**Testing**: pytest + pytest-asyncio with the in-memory FastMCP `Client`; startup-mode tests in a fresh interpreter (pattern from [PR 193](https://github.com/opsmill/infrahub-mcp/pull/193)); the SDK is mocked, no live Infrahub needed for unit tests
**Target Platform**: Linux/macOS server process (MCP over stdio and HTTP)
**Project Type**: Single project, Python MCP server (`src/infrahub_mcp/`)
**Performance Goals**: Instructions under 2,000 characters. No extra Infrahub calls: resources and tools share the existing schema helpers and caches.
**Constraints**: No tool, argument, resource URI or prompt name is removed or renamed. Read-only mode must not mention write tools.
**Scale/Scope**: 1 new module, 1 new config field, 3 resource definitions, about 20 description and error strings, 4 new test files, 1 ADR, documentation updates

## Constitution Check

*GATE: Must pass before implementation.* Checked against `dev/constitution.md` and the `AGENTS.md` boundaries.

- **I. MCP Protocol Compliance**: PASS. Server instructions are part of the MCP initialize and discover results. Resources keep URI templates (RFC 6570 query form). The new tools come from FastMCP's composition API (`add_transform`), not a custom mechanism.
- **II. Infrahub SDK Integration**: PASS. Branch-aware resources call the existing `get_schema_catalog` / `get_schema_detail` helpers, which use the SDK. The existing raw `_get` call in the `infrahub://graphql-schema` resource is unchanged and out of scope.
- **III. Branch-Safe by Default**: PASS. No write path changes. Read-only mode gets its own instructions text without write tools, and the fallback allow-list in `ReadOnlyMiddleware` gains only read-only tools (research R8).
- **IV. Type Safety & Explicit Contracts**: PASS. The new config field is validated by `ServerConfig` at startup. `build_instructions` is fully typed. No `Any` in public interfaces.
- **V. Test Discipline**: PASS. Every requirement has a unit test listed in [contracts/](./contracts/). SC-001 is checked by hand because it depends on model behavior (research R10).
- **VI. Security & Input Boundaries**: PASS. `read_resource` reads through `ctx.fastmcp.read_resource`, so authentication, credential passthrough and audit middleware still apply. A unit test confirms passthrough and audit for `read_resource`. The `branch` query parameter reaches the SDK only as a branch name, as in `get_schema`.
- **VII. Simplicity & Maintainability**: PASS. One function for the guidance text, one FastMCP transform behind one flag. `get_schema` is kept rather than replaced (research R2). Prompt-as-tool and tool renaming are not built (research R1, R3).
- **Ask First: authentication behavior**: Not changed.
- **Ask First: middleware stack order**: Not changed. Only the content of the allow-list in `ReadOnlyMiddleware` changes.
- **Ask First: schema or API contract changes**: Additive only (new server instructions, new optional `branch` on resources, new opt-in tools). Approved by the product owner on 2026-10-12 (spec Clarifications).

No violations. Complexity Tracking omitted.

## Project Structure

### Documentation (this feature)

```text
specs/004-schema-discovery-guidance/
├── spec.md
├── plan.md                         # this file
├── research.md                     # R1-R10 decisions
├── data-model.md                   # config field, instructions text, resource URIs
├── quickstart.md                   # automated and manual verification
├── contracts/
│   ├── server-instructions.md      # target text and rules
│   └── mcp-surface.md              # tool, resource, prompt and config changes
├── checklists/
│   └── requirements.md
└── tasks.md                        # /speckit.tasks output (not created yet)
```

### Source Code (repository root)

```text
src/infrahub_mcp/
├── instructions.py          # NEW: build_instructions(*, read_only, resources_as_tools) -> str
├── server.py                # FastMCP(instructions=...); infrahub_agent uses build_instructions;
│                            # add_transform(ResourcesAsTools(mcp)) when resources_as_tools
├── config.py                # NEW field resources_as_tools: bool = False
├── middleware.py            # _KNOWN_READ_ONLY_TOOLS += 5 names; size-error remediation text
├── resources/schema.py      # infrahub://schema{?branch}; infrahub://schema/{kind}{?branch}
├── tools/schema.py          # get_schema description
├── tools/nodes.py           # get_nodes, search_nodes descriptions, parameters, errors
├── tools/gql.py             # query_graphql description + filter syntax
├── tools/write.py           # node_upsert, mutate_graphql descriptions, parameters, errors
└── prompts/prompts.py       # workflow prompts name get_schema first

tests/unit/
├── test_instructions.py             # NEW: content rules, size, read-only, server wiring
├── test_tool_descriptions.py        # NEW: SC-002 rule over every tool, parameter and prompt
├── test_resources_as_tools.py       # NEW: flag off/on, read-only, passthrough, audit
├── test_schema_resources_branch.py  # NEW: branch templates, parity with get_schema (SC-004)
├── test_server_prompt.py            # UPDATE: infrahub_agent includes build_instructions
└── test_read_only.py                # UPDATE: allow-list entries

docs/docs/references/configuration.mdx   # INFRAHUB_MCP_RESOURCES_AS_TOOLS
docs/docs/references/methods.mdx         # server instructions; branch on schema resources
dev/adr/0009-guidance-in-instructions-and-descriptions.md   # NEW ADR
dev/knowledge/architecture.md            # where model guidance lives
changelog/191.added.md                   # towncrier fragment
CAPABILITIES.md                          # regenerated by its CI job, not edited by hand
```

**Structure Decision**: Single project. The guidance text lives in its own module so it can be tested without importing `server.py`, which reads configuration at import.

## Implementation Phases

Ordered by user story. Each phase can be merged and tested on its own.

### Phase A: Guidance reaches every client (User Story 1, P1)

1. `instructions.py` with `build_instructions`, following [contracts/server-instructions.md](./contracts/server-instructions.md). Tests first.
2. `server.py`: pass `instructions=build_instructions(read_only=_config.read_only, resources_as_tools=_config.resources_as_tools)` to `FastMCP(...)`. Phase A can pass `resources_as_tools=False` until Phase D adds the setting. Rebuild `infrahub_agent` from the persona line plus `build_instructions(...)` plus the tool overview; remove its separate "Data formats" and "Schema discovery" sections.
3. Rewrite descriptions, parameters and error remediations listed in research R9. Add the GraphQL filter syntax to `query_graphql`.
4. `test_tool_descriptions.py`: lists every tool, parameter and prompt through the in-memory client and enforces the SC-002 rule.
5. `ReadOnlyMiddleware._KNOWN_READ_ONLY_TOOLS`: add the five names (research R8).

### Phase B: Use the schema already in context (User Story 2, P2)

Covered by the "do not fetch again" line in Phase A (FR-008). Checked by the content test in `test_instructions.py` and in the manual check in [quickstart.md](./quickstart.md).

### Phase C: Branch-aware resources (User Story 3, P3)

1. `resources/schema.py`: add `infrahub://schema{?branch}`; change the kind template to `infrahub://schema/{kind}{?branch}`; handle `BranchNotFoundError` in the kind resource with a message that names `get_schema()`.
2. `test_schema_resources_branch.py`: all four URI forms from research R4; parity with `get_schema` for the same kind and branch.

### Phase D: Resource tools setting (FR-012, FR-014)

1. `config.py`: `resources_as_tools: bool = False`.
2. `server.py`: after all `mcp.mount(...)` calls, `if _config.resources_as_tools: mcp.add_transform(ResourcesAsTools(mcp))`; pass the setting to `build_instructions` so variants 2 and 4 name the readable URIs (FR-015).
3. `test_resources_as_tools.py` in a fresh interpreter per mode:
   - setting off: `list_resources` and `read_resource` are absent from the tool list;
   - setting on: both are listed, and `read_resource("infrahub://branches")` returns the branch list;
   - setting on with read-only: both are listed and callable;
   - setting on with token passthrough and no credential: `read_resource` is rejected, as a direct resource read is;
   - setting on: the resource read through `read_resource` appears in the audit log.
4. Measure the size of `infrahub://graphql-schema` on the integration test instance. If it is over 500 KB, document the limit (research R3).

### Phase E: Documentation and release

1. `docs/docs/references/configuration.mdx`: new variable. `docs/docs/references/methods.mdx`: server instructions, `branch` on schema resources, the two optional tools. Run `uv run rumdl check docs/docs/`.
2. ADR 0009: model guidance lives in server instructions and tool descriptions; prompts carry workflows; resources serve hosts.
3. `dev/knowledge/architecture.md`: one paragraph on where model guidance lives.
4. Changelog fragment `changelog/191.added.md`; pull request label `changes/minor`.
5. Manual SC-001 check from [quickstart.md](./quickstart.md): 3 runs, at least 2 must pass before merge, all results recorded in the pull request.

## Dependencies and Order

- [PR 193](https://github.com/opsmill/infrahub-mcp/pull/193) should merge first. Phase A reuses its read-only test pattern, and the read-only instructions must agree with its hidden `make_infra_change` prompt. If it has not merged, Phase A can still proceed. The tests for the prompt list in read-only mode then wait for it.
- Phases A, C and D touch different files except `server.py`. A and D both edit `server.py`, so do them in that order.

## Risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| The customer's gateway drops server instructions | Only descriptions reach the model | Descriptions carry the rule on their own (Phase A step 3, SC-002 test). |
| The gateway merges tools without a prefix | `list_resources` / `read_resource` / `get_schema` collide with other servers' tools | The setting is off by default; renaming is deferred until a collision is reported (research R3). |
| The GraphQL schema is over 500 KB | `read_resource` on `infrahub://graphql-schema` fails with the size error | Measured in Phase D; documented if it happens. |
| Model behavior does not improve enough | SC-001 not met (fewer than 2 of 3 runs pass) | The merge waits; the instructions text can be tuned without changing the contract rules. |

## Complexity Tracking

No constitution violations to justify.
