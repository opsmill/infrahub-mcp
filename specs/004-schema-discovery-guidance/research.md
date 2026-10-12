# Research: Schema-Discovery Guidance in Every MCP Client

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-10-12

Each section records one decision, why it was made, and the alternatives that were rejected.

## R1. Channels that carry the schema-first rule

**Decision**: Send the rule in two channels: server instructions, and the tool and parameter descriptions. Keep the `infrahub_agent` prompt, built from the same text.

**Rationale**:

- The MCP specification defines prompts as selected by the user ([MCP prompts](https://modelcontextprotocol.io/specification/2025-06-18/server/prompts)), so the prompt alone does not reach most sessions ([issue 191](https://github.com/opsmill/infrahub-mcp/issues/191)).
- A client may pass server instructions to the model. Claude Code does. The Claude API MCP connector supports only tool calls and passes no instructions ([MCP connector, Limitations](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector)). Which features the customer's gateway passes is not known.
- Tool descriptions are the only text that every client passes to the model, so they must carry the rule on their own.
- The installed MCP SDK (`mcp` 2.2.0) sends the instructions in both `InitializeResult` (protocol 2025-11-25 and earlier) and `DiscoverResult` (protocol 2026-07-28). Source: `mcp/server/lowlevel/server.py:551` and `:675`.

**Alternatives considered**:

- Prompt only (current state). Rejected: does not reach the model unless a user selects it.
- Expose prompts as tools with FastMCP `PromptsAsTools`. Rejected by the product owner on 2026-10-12 (spec FR-013). The assistant would have to know to call `get_prompt("infrahub_agent")`, and an assistant that knows that already has the guidance.
- Descriptions only. Rejected: descriptions are per tool and cannot state an order across tools as clearly as instructions.

## R2. Keep `get_schema`

**Decision**: Keep `get_schema` unchanged as the tool the assistant uses for the schema. Decided by the product owner on 2026-10-12 (spec FR-011).

**Rationale**:

- The tool's name and description carry the schema-first rule in every client. The general-purpose `read_resource` tool is described only as "Read a resource by its URI" (`fastmcp/server/transforms/resources_as_tools.py`), so the rule would depend on server instructions that some clients drop.
- `get_schema` takes one call. Without instructions, `read_resource` needs a `list_resources` call first to learn the URIs.
- `get_schema` accepts `branch` and `expand`. When a kind is not found, it returns the list of valid kinds.
- `get_schema` and the schema resources read through the same helpers (`get_schema_catalog`, `get_schema_detail` in `src/infrahub_mcp/schema.py`), so keeping both does not duplicate logic.
- Removing `get_schema` would break existing callers and would need a major release.

**Alternatives considered**: retire `get_schema` in favor of `ResourcesAsTools`; deprecate it now and decide later. Both rejected for the reasons above.

## R3. General-purpose resource tools behind a setting

**Decision**: Add a `ServerConfig` field `resources_as_tools: bool = False` (environment variable `INFRAHUB_MCP_RESOURCES_AS_TOOLS`). When it is true, `server.py` calls `mcp.add_transform(ResourcesAsTools(mcp))` after all sub-servers are mounted. Decided by the product owner on 2026-10-12 (spec FR-012).

**Rationale**:

- Clients that pass only tools cannot read `infrahub://branches` or `infrahub://graphql-schema` today. No tool returns the same data.
- A local test with FastMCP 4.0.10 (see R4) confirmed that the transform adds exactly two tools, `list_resources` and `read_resource`, and that `read_resource` reads through resource templates, including query parameters.
- The transform reads through `ctx.fastmcp.read_resource`, so the resource middleware still applies: authentication, credential passthrough, audit and resource caching (`resources_as_tools.py` module docstring). A unit test must confirm this for the audit and passthrough middleware.
- Off by default, so clients that already read resources see no new tools.

**Alternatives considered**:

- Always on. Rejected: adds two tools to every client, including clients that already read resources.
- A dedicated tool per resource (for example `get_branches`). Rejected: more code for each resource. The transform covers every current and future resource.
- Rename the tools with an `infrahub_` prefix to avoid collisions in gateways. Not done: the existing tools have no prefix either (`get_schema`, `get_nodes`), so a gateway that does not add a prefix can already produce collisions. To revisit if a gateway user reports one.

**Known limit**: the outer `read_resource` tool call passes through `StrictResponseLimitingMiddleware` (500 KB, `middleware.py:595`). If the GraphQL schema of an instance is larger, reading it through the tool fails with the size error. The size of the GraphQL schema on the test instance must be measured during implementation (tasks). If it exceeds the limit, the documentation states the limit. This feature does not change the size limit.

## R4. Branch-aware schema resources

**Decision**: Keep the static resource `infrahub://schema` (default branch). Add a template `infrahub://schema{?branch}`. Change the kind template to `infrahub://schema/{kind}{?branch}`. All three call the same helpers as `get_schema`, with the server's `schema_expand_peers` setting.

**Rationale**: A local test with FastMCP 4.0.10 gave these results:

| URI read | Handled by |
| --- | --- |
| `infrahub://schema` | the static resource (still listed in `resources/list`, so resource pickers show it) |
| `infrahub://schema?branch=b1` | the `{?branch}` template, `branch="b1"` |
| `infrahub://schema/X` | the kind template, `branch=None` |
| `infrahub://schema/X?branch=b1` | the kind template, `branch="b1"` |
| `read_resource(uri="infrahub://schema/X?branch=b1")` through `ResourcesAsTools` | the kind template, `branch="b1"` |

Existing URIs keep working, so this is not a breaking change.

**Alternatives considered**:

- Path form `infrahub://branch/{branch}/schema/{kind}`. Rejected: adds a second URI for the same data without the branch.
- Turn `infrahub://schema` itself into a template. Rejected: templates are listed separately from resources, and resource pickers may stop showing it.
- Add `expand` to the resources as well. Not done: not needed by the spec. The resources follow the server setting.

## R5. One source for the guidance text

**Decision**: New module `src/infrahub_mcp/instructions.py` with `build_instructions(*, read_only: bool) -> str`. `server.py` passes its result to `FastMCP(instructions=...)`. The `infrahub_agent` prompt includes the same string, followed by the parts that only the prompt carries (the persona line and the tool overview).

**Rationale**: Spec FR-009 requires one source so the prompt and the instructions cannot drift apart. A plain function keeps to the "three similar lines over a premature abstraction" rule of the constitution (principle VII).

**Alternatives considered**: a Markdown file loaded at startup (rejected: the text depends on `read_only`, so it needs code anyway); keeping the text inside `server.py` (rejected: `server.py` is already long, and a separate module can be tested without importing the server).

## R6. Content and size of the instructions

**Decision**: The instructions contain only:

1. the schema-first rule, naming `get_schema()` and `get_schema(kind=...)`, with "never guess" and "do not fetch again if it is already in the conversation";
2. the Infrahub GraphQL filter syntax with one example;
3. how to read TOON;
4. the access mode, and in read-and-write mode the session-branch workflow.

They stay under 2,000 characters. The exact text is in [contracts/server-instructions.md](./contracts/server-instructions.md).

**Rationale**: The MCP blog asks for instructions that cover relations between tools and constraints, not repeated tool descriptions, and for short text ([MCP blog: server instructions](https://blog.modelcontextprotocol.io/posts/2025-11-03-using-server-instructions/)). A gateway that merges several servers' instructions makes length more costly.

**GraphQL example source**: `docs/docs/use-cases/compliance-analysis.mdx` uses `DcimDevice(role__value: "edge") { count edges { node { ... } } }`. Infrahub GraphQL takes filters as arguments of the kind's query.

## R7. Read-only mode

**Decision**: `build_instructions(read_only=True)` leaves out every write tool name and the session-branch workflow. A unit test checks the read-only text against the names of the tools registered in `src/infrahub_mcp/tools/write.py`, so a write tool added later is caught.

**Rationale**: Spec FR-003 and SC-003. This follows the pattern of [PR 193](https://github.com/opsmill/infrahub-mcp/pull/193), which hides the `make_infra_change` prompt in read-only mode with the `"write"` tag.

## R8. Read-only fallback allow-list

**Decision**: Add `list_resources`, `read_resource`, `find_paths`, `find_reachable` and `get_session_info` to `ReadOnlyMiddleware._KNOWN_READ_ONLY_TOOLS` (`src/infrahub_mcp/middleware.py:153`).

**Rationale**: The allow-list is used only when no FastMCP context is available, and it blocks every tool not on it. The two resource tools only read data (spec FR-014). The three other tools are read-only today (`read_only_hint=True`) but missing from the list. Found while reviewing PR 193.

## R9. Description and error-message changes

**Decision**: Replace "read the `infrahub://schema` resource. If your client does not support MCP resources, call the `get_schema` tool instead" with a direct reference to `get_schema` in these places:

| File | Lines (on `stable` at 36b80f9) | Text |
| --- | --- | --- |
| `src/infrahub_mcp/tools/gql.py` | 40-42 | `query_graphql` description; also add the filter syntax (FR-007) |
| `src/infrahub_mcp/tools/nodes.py` | 141, 154, 195-204, 309, 336-337 | `get_nodes` and `search_nodes` descriptions and `kind`/`filters` parameters |
| `src/infrahub_mcp/tools/nodes.py` | 113, 263 | error remediation |
| `src/infrahub_mcp/tools/write.py` | 113, 138, 144, 169-171, 244 | `node_upsert` and `mutate_graphql` descriptions, parameters and errors |
| `src/infrahub_mcp/tools/schema.py` | 51-52 | remove "Prefer reading the resource" (FR-006) |
| `src/infrahub_mcp/middleware.py` | 587 | response-size error remediation |
| `src/infrahub_mcp/prompts/prompts.py` | 41, 58, 103, 113, 155, 168, 170 | workflow prompts: name `get_schema` first, mention the resource second |

**Rationale**: Spec FR-004 to FR-007 and SC-002. A unit test lists every tool, its parameters and its description, and fails if one names an `infrahub://` URI without also naming a tool.

## R10. How SC-001 is checked

**Decision**: Automated tests check the text the server sends (instructions, descriptions, error messages). The reduction in tool calls (SC-001) is checked by hand with Claude through a client that passes only tools, following [quickstart.md](./quickstart.md), and the result is recorded in the pull request.

**Rationale**: Model behavior is not deterministic and needs a live model and a live Infrahub instance. The project has no evaluation harness for model behavior today.
