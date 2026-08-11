# Phase 1 Contracts: MCP tools

The external interface this feature exposes = four MCP tools in `tools/marketplace.py`. All return `str` (JSON or YAML/TOON) consistent with existing tools. Gated by `marketplace_enabled`; install additionally requires not-read-only.

## `marketplace_search` — read

- **Tags**: `{"marketplace", "retrieve"}`; `annotations=ToolAnnotations(readOnlyHint=True)`
- **Params**:
  - `query: str` — free-text search (maps to the API `search=` param)
  - `tag: str | None = None` — filter by tag *(client-side unless a server param is confirmed — see research.md Decision 3 residual)*
  - `namespace: str | None = None` — filter by namespace *(client-side unless confirmed)*
  - `limit: int | None = None` — cap results to a single page; omit to fetch all pages
- **Pagination**: cursor-based internally (`cursor`/`end_cursor` via `page_info`), following SDK PR #1128; not exposed as a tool param.
- **Returns**: compact JSON list of `CatalogEntry` (ranked). Empty list on no matches (not an error).
- **Errors**: `unreachable` on transport/5xx/invalid-JSON.
- **FR**: FR-001, FR-004. *(Endpoint contract confirmed via research.md Decision 3 / SDK PR #1128.)*

## `marketplace_get_schema` — read

- **Tags**: `{"marketplace", "retrieve"}`; `readOnlyHint=True`
- **Params**:
  - `ref: str` — `namespace/name`
  - `version: str | None = None` — pinned version; omit for latest
- **Returns**: `SchemaPayload` (metadata + decompressed YAML).
- **Errors**: `invalid-ref`, `not-found`, `no-such-version` (version 404 when schema exists), `unreachable`. Auto-detect ambiguity (also a collection) → resolves as schema, notes it.
- **FR**: FR-002, FR-004, FR-010, FR-011.

## `marketplace_get_collection` — read

- **Tags**: `{"marketplace", "retrieve"}`; `readOnlyHint=True`
- **Params**: `ref: str` — `namespace/name`
- **Returns**: `CollectionPayload` — metadata + ordered member schemas as a valid multi-document YAML stream (`---`-separated).
- **Errors**: `invalid-ref`, `not-found`, `unreachable`, `too-large` (413).
- **FR**: FR-003, FR-004, FR-010.

## `marketplace_install` — write

- **Tags**: `{"marketplace", "write"}` — `"write"` is mandatory (AGENTS.md); blocked by `ReadOnlyMiddleware` in read-only mode.
- **Params**:
  - `ref: str` — `namespace/name`
  - `version: str | None = None`
- **Behaviour**: resolve ref → download YAML → `get_or_create_session_branch(ctx)` → `client.schema.load(schemas=[...], branch=session_branch)`. Audited via the existing audit middleware path.
- **Returns**: `InstallResult` — reports the session branch + applied summary. Default branch untouched.
- **Errors**: read-only → blocked **before any HTTP call**; ref/network errors as above; schema-validation failure on load → surfaced as the SDK error on the branch, default branch untouched.
- **FR**: FR-005, FR-006, FR-009, FR-012.

## Config contract (`ServerConfig`)

| Field | Env var | Default | Validation |
|-------|---------|---------|------------|
| `marketplace_enabled` | `INFRAHUB_MCP_MARKETPLACE_ENABLED` | `true` | bool |
| `marketplace_url` | `INFRAHUB_MCP_MARKETPLACE_URL` | `https://marketplace.infrahub.app` | well-formed http(s) URL, trailing slash stripped |

## Mounting contract (`server.py`)

```python
if _config.marketplace_enabled:
    mcp.mount(marketplace_mcp)  # read tools
    if not _config.read_only:
        mcp.mount(marketplace_install_mcp)  # write install
```

Disabled → no tools registered, no external call (SC-003).
