# Feature Specification: Infrahub Marketplace integration for the MCP server

**Feature Branch**: `atg-/marketplace-integration`  
**Created**: 2026-07-03  
**Status**: Draft  
**Input**: GitHub issue [opsmill/infrahub-mcp#138](https://github.com/opsmill/infrahub-mcp/issues/138) — "feat: Infrahub Marketplace integration for the MCP server"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Discover and read a marketplace schema (Priority: P1)

An infrastructure engineer, working through their AI assistant, searches the Infrahub Marketplace catalog by keyword (and optionally tag or namespace), picks a result, and reads that schema's details and its actual YAML — all without leaving the conversation to open a browser.

**Why this priority**: Discovery is the foundational capability. Reading a schema's metadata and YAML delivers standalone value (an engineer can evaluate published schemas from the assistant) even if installation is never used. It is read-only and anonymous, so it carries the least risk and unlocks the rest of the flow.

**Independent Test**: With the marketplace serving a public published schema matching "dcim", call the search tool for "dcim", then the get-schema tool for `opsmill/dcim`; confirm a ranked result list is returned and, on the second call, the schema's metadata plus its decompressed YAML.

**Acceptance Scenarios**:

1. **Given** the marketplace has a public published schema matching "dcim", **When** the agent searches for "dcim", **Then** it receives a ranked list of catalog entries with enough metadata (name, namespace, author, version, stats) to judge relevance.
2. **Given** a resolvable reference `opsmill/dcim`, **When** the agent requests that schema, **Then** it receives the schema's catalog metadata plus its decompressed YAML payload.
3. **Given** a reference with a pinned version that exists, **When** the agent requests that version, **Then** it receives exactly that version's YAML rather than the latest.

---

### User Story 2 - Install a marketplace schema into the connected Infrahub (Priority: P2)

An engineer asks the agent to install a chosen marketplace schema into their connected Infrahub instance. The schema is loaded onto a session branch for human review; the default branch is never touched automatically, and promoting the branch to a Proposed Change is left to the existing session flow.

**Why this priority**: Installation is the highest-value action but depends on discovery (P1) and carries write risk, so it ships second and behind explicit safeguards (read-only enforcement, config gating, session-branch isolation).

**Independent Test**: With the server not in read-only mode and marketplace access enabled, call the install tool for `opsmill/dcim`; confirm the schema is loaded onto the session branch, the response reports the branch and what was applied, and the default branch is unchanged.

**Acceptance Scenarios**:

1. **Given** the server is not in read-only mode and marketplace access is enabled, **When** the agent installs `opsmill/dcim`, **Then** the schema is loaded onto the session branch and the response reports the branch and what was applied — the default branch is untouched.
2. **Given** the server is in read-only mode, **When** the agent attempts an install, **Then** it is blocked before any request to the marketplace is made.
3. **Given** downloaded YAML that fails Infrahub's own schema validation, **When** the agent attempts to install it, **Then** the install fails on the session branch with the validation error and the default branch is untouched.

---

### User Story 3 - Adopt a Collection bundle (Priority: P3)

An engineer browses curated Collections (themed bundles of schemas) and fetches an assembled bundle of a collection's member schemas as a single multi-document YAML stream, so they can adopt a "starter pack" in one step.

**Why this priority**: Collections are a convenience layer over single-schema discovery. Valuable but not required for the core discover→read→install loop, so it ships last.

**Independent Test**: With a public collection `opsmill/starter`, call the get-collection tool; confirm the collection's ordered member schemas are returned as a valid multi-document YAML stream.

**Acceptance Scenarios**:

1. **Given** a public collection `opsmill/starter`, **When** the agent requests that collection, **Then** it receives the collection's metadata and its ordered member schemas as a valid multi-document YAML stream.

---

### Edge Cases

- **Marketplace unreachable or returns a server error (5xx)** → surfaced as a distinct "cannot reach the marketplace" error, clearly separate from "not found".
- **A `namespace/name` reference matches both a schema and a collection** → resolved deterministically (schema wins), with the ambiguity surfaced, matching `infrahubctl marketplace` behaviour.
- **A pinned version does not exist though the schema does** → reported as "no such version", not a generic not-found.
- **A collection bundle exceeds the marketplace's size cap** → the marketplace returns a "too large" (413) response; the server relays a clear "too large" message.
- **Install attempted while in read-only mode** → blocked before any HTTP call to the marketplace.
- **Marketplace access disabled by config** → the tools are absent entirely; the agent gets no partial capability and no external request is made.
- **An invalid or malformed reference** → reported as "invalid ref", distinct from "not found".

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The server MUST expose a read-only capability to search the marketplace catalog by free-text query, with optional tag and namespace filters and pagination.
- **FR-002**: The server MUST expose a read-only capability to retrieve a schema's catalog metadata and its YAML payload, resolving a `namespace/name` reference and accepting an optional pinned version.
- **FR-003**: The server MUST expose a read-only capability to retrieve a collection's metadata and its assembled member-schema YAML.
- **FR-004**: Marketplace read capabilities MUST be marked read-only and MUST return only public, published content.
- **FR-005**: The server MUST expose a write-tagged capability that installs a marketplace schema into the connected Infrahub via the Infrahub SDK, isolated to a session branch.
- **FR-006**: The install capability MUST be blocked by the existing read-only enforcement when the server is in read-only mode.
- **FR-007**: Marketplace access MUST be gated by a configuration flag; when disabled, marketplace capabilities MUST NOT be registered or callable. The flag defaults to **enabled** — discovery works out of the box on a fresh install, and admins who wish to prevent any outbound call disable it.
- **FR-008**: The marketplace base URL MUST be configurable, defaulting to `https://marketplace.infrahub.app`.
- **FR-009**: Marketplace requests MUST NOT include Infrahub credentials and MUST honour the connected SDK's proxy and TLS configuration.
- **FR-010**: The server MUST distinguish and clearly report "not found", "invalid ref", "cannot reach marketplace", and "too large" conditions without leaking internal detail.
- **FR-011**: When a `namespace/name` resolves to both a schema and a collection, the server MUST resolve deterministically (schema wins) and surface the ambiguity, matching `infrahubctl` behaviour.
- **FR-012**: Install actions MUST be recorded through the same audit path as other write operations.

### Key Entities *(include if feature involves data)*

- **Schema** *(marketplace, external)*: A published catalog entry keyed by `(namespace, name)` — the thing an agent searches for and installs. Maps onto the connected instance's schema on install.
- **Schema Version** *(marketplace, external)*: The immutable, semver'd YAML payload actually downloaded and loaded.
- **Collection** *(marketplace, external)*: An ordered bundle of Schemas; adopting one fans out to its member schemas.
- **Session branch** *(existing)*: The isolation boundary an install lands on — reused unchanged from the existing write conventions.
- **Server configuration** *(existing, extended)*: Gains a marketplace base URL and a marketplace-enabled flag, validated at startup.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An engineer can go from "find a DCIM schema" to reading its YAML entirely within the assistant, with no browser step.
- **SC-002**: An engineer can adopt a published schema into their Infrahub for review in under a minute, and it never appears on the default branch without approval.
- **SC-003**: With marketplace access disabled, no marketplace capability is reachable and no external request is made.
- **SC-004**: A failed marketplace interaction tells the operator whether the problem is the reference, the content, or the service — in a single message.

## Assumptions

- The marketplace public API stays stable with anonymous read access to public, published content (consistent with `infrahubctl marketplace`).
- "Installing" a schema means loading its YAML into the connected Infrahub via the SDK's schema-load path onto a session branch; promoting the branch to a Proposed Change follows the existing session conventions and is not automated here.
- **v1 installs only the named schema**; the marketplace's tracked cross-schema dependencies are not followed automatically (out of scope below).
- Agents adopting external schemas is acceptable default behaviour, so marketplace access is enabled by default; admins who disagree disable the flag.
- No new runtime dependency is required — the HTTP client (`httpx`) is already available via the Infrahub SDK.

## Out of Scope

- Publishing, forking, upvoting, reviewing, or any authenticated/write operation *against the marketplace itself*.
- Marketplace user accounts, API tokens, or namespace management from the MCP server.
- Automatic dependency resolution across schemas (v1 installs only what is asked for).
- Automatically turning the session branch into a Proposed Change (left to the existing session flow / the user).

## Governance Gates Crossed

- [x] API / public interface change *(new MCP tools/resources)*
- [x] Authentication / authorization change *(new external-service call path + a new write tool; requires sign-off per AGENTS.md "Ask First")*
- [ ] New dependency *(none — `httpx` already present via the SDK)*
- [ ] Database schema or migration change
- [ ] CI/CD workflow change
