# 8. Marketplace client bypasses the SDK for its own API, loads into Infrahub via the SDK

**Status:** Accepted
**Date:** 2026-07-03
**Author:** @agittings

## Context

The Infrahub Marketplace (`marketplace.infrahub.app`) is a separate public service from a connected Infrahub instance. Integrating it (issue #138) required an HTTP client against the marketplace's `/api/v1` API for search, schema/collection detail, and versioned download.

Constitution II ("Infrahub SDK Integration") forbids direct HTTP calls **to the Infrahub API** — all Infrahub operations must go through `infrahub-sdk`. A naive reading ("never raw HTTP") would forbid a marketplace client too. But the SDK exposes marketplace access only as a `typer` CLI (`infrahub_sdk.ctl.marketplace`) — there is no importable client, only the CLI plus a `marketplace_url` config default.

## Decision

Draw the SDK boundary at the **Infrahub instance**, not at "any HTTP":

- **Marketplace reads** go through a net-new `MarketplaceClient` (`src/infrahub_mcp/marketplace.py`) — a thin async `httpx` client that mirrors the URL scheme and schema-vs-collection auto-detect of `infrahub_sdk.ctl.marketplace`, and the list/search/detail endpoint contract from infrahub-sdk-python PR #1128. This is a *different service*, so direct HTTP is correct here.
- **The install-side load into Infrahub** goes through the SDK (`client.schema.load(...)`) onto a session branch — never raw HTTP to Infrahub.
- The marketplace client carries **no Infrahub credentials** and inherits only the SDK config's proxy/TLS settings (`make_marketplace_http_client`).

## Consequences

### Positive

- Reaching an external service cannot leak internal Infrahub secrets (Constitution VI); proxy/TLS still honoured for corporate networks.
- The install path stays branch-safe and SDK-mediated (Constitution II/III): the write is `"write"`-tagged, session-branch isolated, blocked by `ReadOnlyMiddleware`, and audited like any other tool call.
- `MarketplaceClient` is free of MCP/Infrahub coupling, so it is unit-testable against a mock httpx transport.

### Negative

- We reimplement URL/semantics the SDK CLI already encodes (no importable client to reuse). Mitigated by mirroring `ctl.marketplace` closely and citing it.
- The marketplace **search** endpoint contract is confirmed only via PR #1128 (still open at time of writing); its `tag`/`namespace` filters are applied client-side until a server param is confirmed.

### Neutral

- Marketplace access is gated by `marketplace_enabled` (default on) and `marketplace_url`, validated at startup — consistent with [0006](0006-config-validation-at-boundary.md).

## Alternatives Considered

### Shell out to `infrahubctl marketplace`

Rejected: brittle, couples us to CLI output formatting and process management.

### Wait for an importable SDK marketplace client

Rejected: none exists; #1128 adds only more CLI commands, not a client.

### Route the schema load through raw GraphQL

Rejected: forbidden by Constitution II; `_BLOCKED_MUTATIONS` in `tools/write.py` already blocks schema mutations. The SDK `schema.load` path is the sanctioned route.
