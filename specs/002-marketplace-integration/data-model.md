# Phase 1 Data Model: Marketplace integration

No persisted storage. These are transient typed models returned by `MarketplaceClient` and the tools. Prefer Pydantic models (`frozen=True` where immutable) per Principle IV.

## MarketplaceIdentifier

Parsed reference to a catalog item.

| Field | Type | Notes |
|-------|------|-------|
| namespace | str | non-empty, from `namespace/name` |
| name | str | non-empty |

- **Validation**: input string MUST split into exactly two non-empty parts on `/`; else `invalid-ref` error (mirrors CLI `_parse_identifier`).

## CatalogEntry (search result)

One ranked result from `marketplace_search`.

| Field | Type | Notes |
|-------|------|-------|
| namespace | str | |
| name | str | |
| title / description | str \| None | for relevance judgement (US1 scenario 1) |
| author | str \| None | |
| latest_version | str \| None | semver |
| tags | list[str] | |
| item_type | "schema" \| "collection" | |
| stats | dict \| None | e.g. downloads/stars, if provided |

- **Note**: exact fields depend on the search endpoint contract (research.md Decision 3 — to confirm). Model tolerates missing optional fields.

## SchemaPayload

Returned by `marketplace_get_schema`.

| Field | Type | Notes |
|-------|------|-------|
| identifier | MarketplaceIdentifier | |
| resolved_version | str | from `x-schema-version` header or requested version; "latest" fallback |
| yaml | str | decompressed schema YAML (the reviewable artifact) |
| metadata | dict \| None | catalog metadata when available |

## CollectionPayload

Returned by `marketplace_get_collection`.

| Field | Type | Notes |
|-------|------|-------|
| identifier | MarketplaceIdentifier | |
| members | list[MarketplaceIdentifier] | ordered member schemas |
| yaml | str | assembled multi-document YAML stream (US3) — `---`-separated, valid multi-doc |
| metadata | dict \| None | collection metadata |

## InstallResult

Returned by `marketplace_install`.

| Field | Type | Notes |
|-------|------|-------|
| identifier | MarketplaceIdentifier | what was installed |
| resolved_version | str | version loaded |
| branch | str | session branch it landed on (never the default branch) |
| applied | summary | SDK `SchemaLoadResponse` summary of what changed |

## MarketplaceError categories (enum)

`invalid-ref` · `not-found` · `no-such-version` · `unreachable` · `too-large`
(see research.md Decision 4). Each maps to a sanitised MCP error message + remediation; never carries internal detail.

## Relationships / flow

```
search() -> [CatalogEntry]        (read, anonymous)
get_schema(ref, version?) -> SchemaPayload
get_collection(ref) -> CollectionPayload   (members fan out to schema downloads)
install(ref, version?) -> InstallResult    (write; session branch via SDK schema.load)
```

Auto-detect: `ref` with no explicit type probes schema+collection; schema wins on tie (FR-011).
