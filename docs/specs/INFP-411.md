# INFP-411 — Infrahub MCP Server Phase 2

**Jira:** [INFP-411](https://opsmill.atlassian.net/browse/INFP-411)
**Status:** In progress (split rollout)
**Owner:** Benoit Kohler

## Product goal

Build deployment packaging, authentication, operational controls, and documentation for the Infrahub MCP server so it is a first-class, production-ready component of Infrahub deployments rather than a tool users install and manage separately. This lets customers run the MCP server alongside Infrahub, connect AI agents under their own identity, and govern write operations through read-only mode and branch isolation.

## Rollout strategy

The work was originally staged on a single branch (`feat/add-middleware`, ~6.4k additions across 48 files) tracked in PR #62. That PR has been split into six reviewable slices so each concern ships independently and can be reverted without rolling back unrelated work.

Branch topology (hybrid stack): PRs 1 → 2 → 3 are stacked (they genuinely depend on each other); PRs 4, 5, 6 branch off the parent of PR 3 and can review in parallel once PR 3 lands.

```text
stable
 └── feat/mw-config (PR 1, this PR)
      └── feat/mw-readonly (PR 2)
           └── feat/mw-auth (PR 3)
                ├── feat/mw-prod (PR 4)          ◀── parallel
                ├── feat/mw-observability (PR 5) ◀── parallel
                └── feat/mw-compat (PR 6)        ◀── parallel
```

## Slice → INFP-411 requirement mapping

| # | Slice | INFP-411 requirement(s) | Spec |
|---|---|---|---|
| 1 | Foundation — `ServerConfig` + middleware scaffold | (enables everything; no user-visible requirement on its own) | this file |
| 2 | Read-only mode + GraphQL read/write separation | #5 Read-Only Mode, #6 partial (mutation blocking) | [INFP-411-pr2-read-only.md](./INFP-411-pr2-read-only.md) |
| 3 | Authentication (OIDC + token-passthrough) | #4 Authentication — HTTP Transport. Closes open question #8 (MCP spec and token pass-through). | [INFP-411-pr3-auth.md](./INFP-411-pr3-auth.md) |
| 4 | Production middleware — rate limiting, caching, retries, error handling | (hardening that exceeds INFP-411 spec) | [INFP-411-pr4-production-middleware.md](./INFP-411-pr4-production-middleware.md) |
| 5 | Observability — request IDs, structured logging, timing, OTel, Prometheus, audit, health | #7 Health Check Endpoint, plus extra instrumentation not in INFP-411 | [INFP-411-pr5-observability.md](./INFP-411-pr5-observability.md) |
| 6 | Session/compat — branch-per-session, DereferenceRefs, Ping | #6 Branch Targeting. Closes open question #4 (branch naming convention). | [INFP-411-pr6-session-compat.md](./INFP-411-pr6-session-compat.md) |

Requirements #1 (Container Image & Registry), #2 (Docker Compose Integration), and #3 (Helm Chart Integration) live in the `infrahub-helm` and Infrahub repos, not in this one. Requirement #8 (Documentation) is shipped incrementally by each slice that introduces user-visible surface.

## INFP-411 checklist (Product view)

Mirrors the Jira idea's Product Checklist. Updated as slices land.

- [x] Goals defined [shaping]
- [x] Discovery [use case + needs]
- [x] Solution defined
- [ ] Solution VALIDATED
- [ ] Development complete [PR merged] — 0 / 6 slice PRs merged
- [ ] Testing complete
- [ ] Documentation complete

## Ongoing state / source of truth

- **This umbrella doc:** frozen-in-time at merge of each slice. Do not retroactively rewrite history here; update the checklist and link the PR.
- **Jira INFP-411:** the living rollup. Comment on it after each slice merges with a link to the PR + slice spec.
- **Code:** source of truth for current behavior. When in doubt, trust the code over the spec.
