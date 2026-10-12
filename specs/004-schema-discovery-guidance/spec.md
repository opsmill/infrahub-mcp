# Feature Specification: Schema-Discovery Guidance in Every MCP Client

**Feature Branch**: `feat/schema-discovery-guidance` (speckit feature `004-schema-discovery-guidance`)
**Created**: 2026-10-12
**Status**: Draft
**Input**: User description: "Schema-discovery guidance reaches agents in every MCP client ([issue 191](https://github.com/opsmill/infrahub-mcp/issues/191)). Decide whether the FastMCP transforms that expose resources and prompts as tools can replace the schema tool."

## Background

Agents that connect to the Infrahub MCP server receive the rule "read the schema first, never guess kind names or filter keys" only when a user selects the `infrahub_agent` prompt by hand. Most users never do, and an agent behind an MCP gateway or inside a chat bot has no user to select it. In a field test against Infrahub 1.11 with `infrahub-mcp` 1.2.0, a customer using Claude through an MCP gateway asked "how many services of type X are there?". The agent needed six tool calls where two would have answered: it guessed a kind name, wrapped GraphQL filters in a `filters: {...}` argument that Infrahub does not accept, and only then read the schema ([issue 191](https://github.com/opsmill/infrahub-mcp/issues/191), [Slack thread](https://opsmillworkspace.slack.com/archives/C097VES871D/p1791730538007749)).

Facts that shape this specification:

- The MCP specification defines prompts as selected by the user, and resources as included by the host application. Neither reaches the model on its own ([MCP prompts](https://modelcontextprotocol.io/specification/2025-06-18/server/prompts), [MCP resources, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)).
- Server instructions and tool descriptions are the two channels a server can use to reach the model without a user action. A client may pass server instructions to the model, but is not required to ([MCP blog: server instructions](https://blog.modelcontextprotocol.io/posts/2025-11-03-using-server-instructions/)).
- The Claude API MCP connector supports only tool calls. It passes no resources, prompts or server instructions to the model ([Claude MCP connector, Limitations](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector)). Which features the customer's gateway passes on is not known.
- Today the tool descriptions and parameter descriptions point the agent to the `infrahub://schema` resource first, and to the `get_schema` tool only "if your client does not support MCP resources". The schema resources always read the default branch. `get_schema` accepts a branch.
- FastMCP 4.0.10, the version the project uses, can expose resources as two general-purpose tools (`list_resources`, `read_resource`) and prompts as two general-purpose tools (`list_prompts`, `get_prompt`).

## Clarifications

### Session 2026-10-12

- Q: Keep `get_schema`, or retire it in favor of the general-purpose `read_resource` tool? → A: Keep `get_schema` (FR-011).
- Q: Should clients that pass only tools be able to read the branch list and the GraphQL schema? → A: Yes, through a setting that is off by default (FR-012).
- Q: Should prompts be exposed as tools? → A: No (FR-013).
- Q: Should the server instructions also say which tool to use for common questions? → A: Yes: `get_nodes` for nodes of one kind, including counts through `total_count`; `find_paths` and `find_reachable` for connectivity and impact questions (FR-001).
- Q: When the resource tools setting is on, should the instructions name the URIs `read_resource` can read? → A: Yes, one line, only when the setting is on (FR-015).
- Q: How is SC-001 checked before merge? → A: Run the scenario 3 times with Claude through a client that passes only tools; the pull request merges only if at least 2 runs pass (SC-001).
- Q: Should `infrahub://graphql-schema` also accept a branch in this feature? → A: No, out of scope; tracked in a separate issue together with the raw HTTP call that resource uses (Assumptions).
- Q: Should the spec cover how filter keys differ between `get_nodes` and GraphQL? → A: Yes; it is part of the instructions and descriptions this feature changes (FR-016, FR-017, SC-006).
- Q: In read-and-write mode, should the instructions say that reads stay on the default branch and how to read the session branch? → A: Yes, one sentence: reads use the default branch unless `branch` is passed; `get_session_info` returns the session branch (FR-001).
- Q: `get_nodes` ignores `limit` (see Assumptions). How does this feature handle it? → A: A separate bug fix merges first; this feature depends on it and keeps the `get_nodes` rule for counts (FR-001, Assumptions).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Answer a question without guessing the schema (Priority: P1)

A network engineer asks an assistant "how many services of type X are there?". The assistant is connected to the Infrahub MCP server through a client or gateway that passes only tools to the model. The assistant reads the schema for the relevant kind, then runs one query with valid filter names, and answers.

**Why this priority**: This is the failure reported in issue 191. It affects every client where nobody selects the `infrahub_agent` prompt, which is the normal case, and every client that passes only tools.

**Independent Test**: Connect a client that exposes only tools, without selecting any prompt. Ask a counting question about a kind the assistant cannot know in advance. Count the tool calls and check that none of them uses a guessed kind name or an invalid filter argument.

**Acceptance Scenarios**:

1. **Given** a client that passes only tools to the model and no prompt selected, **When** the engineer asks a question about nodes of a kind, **Then** the tool list and tool descriptions that the assistant receives name the schema step as the step to take before querying, and name it as a tool the assistant can call.
2. **Given** a client that passes server instructions to the model, **When** the session starts, **Then** the assistant receives the schema-first rule, the GraphQL filter syntax rule and the current access mode (read-only, or read and write) without anyone selecting a prompt.
3. **Given** a parameter description or error message that refers the assistant to the schema, **When** the assistant reads it in any client, **Then** it names a step the assistant can take with the tools it has.
4. **Given** the assistant has read the filter keys of a kind with `get_schema`, **When** it writes a GraphQL query, **Then** the descriptions it received say that the same keys are arguments of the kind's query, not a `filters` argument.
5. **Given** the assistant sends a GraphQL query with a `filters` argument, **When** Infrahub rejects it, **Then** the error the assistant receives names the mistake and shows the correct form, so the next query is correct.

---

### User Story 2 - Use the schema already in context (Priority: P2)

A network engineer using a desktop client attaches the Infrahub schema catalog as context before asking questions. The assistant uses the attached schema and does not fetch it again.

**Why this priority**: Resources still serve clients where the user or the host attaches them. The guidance from User Story 1 must not cause duplicate schema reads in those clients.

**Independent Test**: In a client that supports resources, attach `infrahub://schema` and ask a question about a kind in the catalog. Check whether the assistant reads the catalog again.

**Acceptance Scenarios**:

1. **Given** the schema catalog is already in the conversation, **When** the engineer asks about a kind it lists, **Then** the guidance tells the assistant not to fetch the catalog again.

---

### User Story 3 - Read the schema of a session branch (Priority: P3)

A network engineer has an assistant add a kind on a session branch, then asks a question about nodes of that kind on that branch. The assistant reads the schema of the session branch, not of the default branch.

**Why this priority**: The schema tool already supports a branch. The resources do not, so a client that reads the resources on a session branch gets a different schema from the tool.

**Independent Test**: Load a schema change on a branch. Read the kind's schema through the tool and through the resource, both for that branch, and compare.

**Acceptance Scenarios**:

1. **Given** a kind that exists only on branch B, **When** the schema is read for branch B through the tool or the resource, **Then** both return the kind.

---

### Edge Cases

- The client passes neither server instructions nor prompts. The tool and parameter descriptions alone must carry the schema-first rule.
- The server runs in read-only mode. The instructions must not mention write tools, the same way read-only mode hides the `make_infra_change` prompt ([PR 193](https://github.com/opsmill/infrahub-mcp/pull/193)).
- A gateway merges the instructions of several servers. The instructions must name Infrahub tools by their names, so the rule still applies after merging.
- The same filter keys are used in two forms: as keys of the `filters` argument of `get_nodes`, and as arguments of the kind's query in GraphQL. The `get_schema` output lists them under the label `filters`. An assistant that reads this label can carry the `filters` wrapper into GraphQL, as in calls 3 and 5 of the field test.
- A gateway merges the tools of several servers. General-purpose tool names such as `read_resource` or `get_prompt` can collide with tools of the same name from other servers. Whether the customer's gateway adds a prefix is not known.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The server MUST send server instructions that state, in this order of importance:
  - read the schema with `get_schema` before querying a kind whose name or filter keys are not known;
  - never guess kind names or filter keys;
  - use `get_nodes` for nodes of one kind, including counts through its `total_count`, before writing GraphQL;
  - use `find_paths` and `find_reachable` for questions about how nodes are connected or what a change affects;
  - in Infrahub GraphQL, filters are arguments of the kind's query, not a `filters` argument;
  - results use TOON format;
  - the current access mode;
  - in read-and-write mode: read tools use the default branch unless a `branch` is passed, and `get_session_info` returns the session branch to pass when reading changes made in this session.
- **FR-002**: The server instructions MUST NOT repeat what each tool description already says ([MCP blog: server instructions](https://blog.modelcontextprotocol.io/posts/2025-11-03-using-server-instructions/)).
- **FR-003**: In read-only mode, the server instructions MUST NOT mention write tools or the branch-per-session write workflow.
- **FR-004**: The descriptions of `get_nodes`, `search_nodes`, `query_graphql`, `node_upsert` and their `kind` and `filters` parameters MUST name `get_schema` as the step for finding valid kind names and filter keys. They MUST NOT make the step depend on whether the client supports resources.
- **FR-005**: Error messages that send the assistant to the schema MUST name `get_schema`.
- **FR-006**: The `get_schema` description MUST state that it is the step to take first. It MAY mention that the same data is available as the `infrahub://schema` resource for hosts that attach it, and MUST NOT tell the assistant to prefer the resource.
- **FR-007**: The `query_graphql` description MUST state the Infrahub GraphQL filter syntax, with one example.
- **FR-008**: The server instructions MUST tell the assistant not to fetch the schema again when it is already in the conversation.
- **FR-009**: The `infrahub_agent` prompt MUST include the same guidance text as the server instructions, from one source, so the two cannot drift apart.
- **FR-010**: The schema resources (`infrahub://schema`, `infrahub://schema/{kind}`) MUST accept an optional branch, and return the same data as `get_schema` for the same kind and branch. The GraphQL schema resource is out of scope (see Assumptions).
- **FR-011**: The server MUST keep `get_schema` as the tool the assistant uses to read the schema. Its name, arguments and output do not change.
- **FR-012**: An operator MUST be able to turn on, through one setting that is off by default, two general-purpose tools that list and read every resource the server offers. With the setting on, a client that passes only tools can read the branch list and the GraphQL schema. With the setting off, the tool list does not change.
- **FR-013**: The server MUST NOT expose prompts as tools. Prompts stay selected by the user, as the MCP specification defines them.
- **FR-014**: In read-only mode, the two general-purpose resource tools MUST be allowed, because they only read data.
- **FR-015**: When the resource tools setting is on, the server instructions MUST name the URIs of the branch list (`infrahub://branches`) and the GraphQL schema (`infrahub://graphql-schema`) as readable with `read_resource`. When the setting is off, the instructions MUST NOT mention `read_resource` or `list_resources`.
- **FR-016**: When Infrahub rejects a `query_graphql` query because of an unknown `filters` argument, the error MUST state that filter keys are arguments of the kind's query and MUST show the correct form, using the kind name from the rejected query when the server can read it. The server adds this text itself, so it reaches the model in every client.
- **FR-017**: The `get_schema` description and the description of the `filters` parameter of `get_nodes` MUST state that the same keys are used as GraphQL arguments in `query_graphql`, placed directly on the kind's query and not in a `filters` argument. The `get_schema` output does not change (FR-011).

### Key Entities

- **Schema-discovery guidance**: The text that tells the assistant to read the schema first, which tool to use for common questions, how to write Infrahub GraphQL filters and which access mode is active. It has four variants, one for each combination of read-only mode and the resource tools setting. Sent as server instructions and included in the `infrahub_agent` prompt.
- **Tool and parameter descriptions**: The text each client passes to the model with the tool list. The only channel that reaches the model in every client.
- **Schema resources**: `infrahub://schema` and `infrahub://schema/{kind}`, for hosts and users who attach the schema as context.
- **Resource tools setting**: The operator setting that adds the two general-purpose resource tools (FR-012).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the issue 191 scenario, with a client that passes only tools and no prompt selected, the assistant answers in at most 3 tool calls, with no call that uses a guessed kind name or a `filters` argument in GraphQL. The baseline is 6 tool calls. The scenario is run 3 times before merge; at least 2 runs must pass, and the results are recorded in the pull request. The merge waits on this check.
- **SC-002**: No tool description, parameter description or error message tells the assistant to read a resource without also naming a tool it can call for that step.
- **SC-003**: In read-only mode, nothing the server sends to the model names a write tool.
- **SC-004**: For every kind and branch, the schema resource and `get_schema` return the same data.
- **SC-005**: With the resource tools setting on and only tools passed to the model, the assistant can read the branch list in one tool call.
- **SC-006**: Every `query_graphql` error caused by a `filters` argument contains the correct form, with the kind name from the rejected query when the query names one kind.

## Assumptions

- The customer's gateway passes tool names and descriptions to the model unchanged. Whether it passes server instructions, prompts or resources is not known, so every requirement in User Story 1 must work with tools alone.
- A fix for `get_nodes` paging merges before this feature. `get_nodes` calls the SDK with `parallel=True` (`src/infrahub_mcp/tools/nodes.py:60`). In that mode, SDK `client.filters` requests every page of the result and applies `limit` to each page, not to the whole result; with an `offset`, every page uses the same offset. A test with a mocked transport and 1,000 nodes gave these results: `limit=50` without offset made 20 GraphQL calls and returned all 1,000 nodes; `limit=50, offset=100` made 20 calls and returned 1,000 nodes of which 50 were unique. The existing pagination tests mock `_fetch_nodes`, so they do not catch it. FR-001 tells the assistant to count with `get_nodes`, which is only cheap once `limit` is applied. The fix is tracked in its own issue and pull request, and the SDK behavior is reported to the Infrahub SDK maintainers.
- PR 193 is merged before this feature, and this feature reuses its `"write"` tag to hide write content in read-only mode.
- SC-001 is measured with Claude, the model used in the field test. Results with other models are not known.
- Changing descriptions, adding server instructions and adding an optional branch to the resources does not change any existing tool name, argument or resource URI, so existing callers are not broken.
- The general-purpose resource tools use the names FastMCP gives them (`list_resources`, `read_resource`). The existing tools also have names without an Infrahub prefix (`get_schema`, `get_nodes`), so a gateway that does not add a prefix can already produce collisions. Renaming is out of scope.
- Out of scope: a branch for `infrahub://graphql-schema`. It keeps reading the default branch. On a session branch, `get_schema(kind=..., branch=...)` returns the attributes and relationships needed to write a query. A separate issue covers the branch and the raw HTTP call the resource uses (`src/infrahub_mcp/resources/schema.py:92`).
