# Phase 0 Research: Session Branch Recovery & Reset

All `NEEDS CLARIFICATION` items from Technical Context are resolved below. Findings come from the installed packages in this repo's venv (`fastmcp==3.2.4`, `infrahub-sdk==1.20.0`, Python 3.13.5) and the existing source.

## R1 — Detecting a merged / read-only branch (resolves the deferred "detection mechanism" decision)

- **Decision**: Detect **proactively** by inspecting `BranchData.status` returned from the `client.branch.get()` call that `get_or_create_session_branch` already performs. Treat `status ∈ {MERGED, DELETING}` as "unwritable → recover" and `BranchNotFoundError` as "missing → recover" (existing behavior). `OPEN`, `NEED_REBASE`, `NEED_UPGRADE_REBASE` remain writable.
- **Rationale**:
  - `infrahub_sdk/branch.py` defines `class BranchStatus(str, Enum)` with `OPEN, NEED_REBASE, NEED_UPGRADE_REBASE, DELETING, MERGED`, and `BranchData.status: BranchStatus` (default `OPEN`). When a branch is merged its `status` becomes `MERGED`. This is the **only** field that reliably indicates read-only state (the other fields — `is_default`, `sync_with_git`, `has_schema_changes`, `graph_version` — do not flip on merge).
  - The #110 fix already calls `await client.branch.get(branch_name=...)` on every write to validate existence. Reading `.status` from that same response adds **zero** extra round-trips — it is the cheapest possible mechanism and fits Principle VII (Simplicity).
- **Reactive net (REQUIRED — FR-011, raised from "optional" by critique E2)**: A merge can happen in the TOCTOU window between `branch.get()` and the actual write. The write paths catch a read-only/merged-looking `GraphQLError` (substring pre-filter) and then **confirm the branch is actually MERGED/DELETING/missing via `client.branch.get()` before clearing** — a substring match alone is a false-positive risk (a read-only *attribute* error reads identically and would wrongly orphan the user's work; this was caught in code review). Only on confirmed staleness do they clear the cached branch (under the per-session lock) and raise an actionable retryable `ToolError`. We deliberately do **not** blindly replay the failed mutation — an arbitrary `mutate_graphql` could partially apply. Clearing + retryable error guarantees the session never stays wedged (SC-001).
- **Alternatives considered**:
  - *Reactive-only* (catch the write error, recover, retry): works but performs a doomed write first, and matching server error strings is brittle. Rejected as the primary mechanism; kept only as the optional net above.
  - *A dedicated writability endpoint*: none exists on `client.branch.*` (`get`, `all`, `create`, `delete`, `rebase`, `validate`, `merge`, `diff_data`).

## R2 — Per-session scoping, identity & cleanup (resolves FR-010 / Q3; revised by critique E1)

- **Decision**: Store the session branch **keyed by the per-session object** (`ctx.request_context.session`) in `weakref.WeakKeyDictionary` maps on the (shared) `AppContext` — one for the branch name, one for the per-session lock — plus a small guard lock for lazy lock creation. The scalar `session_branch: str | None` is removed.
- **Why the session OBJECT, not the `session_id` string (critique E1)**: a `dict[str, str]` keyed by `session_id` on the process-wide `AppContext` would **never be cleaned up** — every HTTP session mints a new id, so the dict grows unbounded for the server's life. There is no session-close hook that maps to such a dict (FastMCP's `ctx.set_state/get_state` is **per-request** — `_request_state`, `fastmcp/server/context.py:207,1264` — not per-session). A `WeakKeyDictionary` keyed by the session object **auto-evicts** when that session object is garbage-collected at session end → true per-session scope (FR-010) with no leak and no manual bookkeeping. FastMCP itself stashes per-session data on the session object (`session._fastmcp_state_prefix`, context.py:686), so the object is the natural per-session anchor.
- **Identity properties**: `ctx.request_context.session` is the **same object** across all tool calls within one client session and a **distinct object** per session (confirmed in `mcp/shared/context.py` `RequestContext.session`; FastMCP wraps it). ServerSession instances are normal objects → weak-referenceable and identity-hashable, so they work as `WeakKeyDictionary` keys. (`ctx.session_id` is still fine for **display/logging** in `get_session_info`, but not used as a storage key.)
- **Lifespan-scope ambiguity, intentionally sidestepped**: the MCP low-level layer enters the lifespan per session (`mcp/server/lowlevel/server.py:657`), but FastMCP caches the result process-wide (`_lifespan_result`); #110's commit message + the reported bug confirm `AppContext` is in practice **shared across sessions**. Keying by the session object is correct under either scope.
- **Fallback / guard**: if `ctx.request_context` or its `session` is `None` (should not happen from a tool call), raise the existing `request_context must not be None` error.
- **Alternatives considered**:
  - *`dict[str, str]` keyed by `ctx.session_id`*: rejected — unbounded growth / leak (critique E1).
  - *Stash the branch as an attribute directly on the session object*: viable (mirrors FastMCP) and also auto-cleans, but monkey-patches a third-party object and is harder to introspect/test; `WeakKeyDictionary` keeps state on our `AppContext`.
  - *Rely on a fresh per-session `AppContext`*: rejected — contradicted by the observed bug and `_lifespan_result` caching.

## R3 — Validating an explicit target branch name against the convention (resolves Q2 / FR-006)

- **Decision**: A target branch name "conforms to the convention" iff it matches a regex derived from the configured `branch_pattern`. Build the regex by escaping the literal segments and substituting placeholders: `{date}→\d{8}`, `{hex}→[0-9a-f]{8}`, `{user}→[A-Za-z0-9._/-]+` (the sanitized-user charset), anchored `^…$`. If `branch_pattern` has no placeholders (fixed name), conformance means an exact match to that name. The name must additionally pass the allowed branch charset (Principle III: alphanumeric, hyphen, underscore, dot, slash). Conformant → create + tell the caller; non-conformant → `ToolError` with guidance; never silently reroute.
- **Rationale**: `ServerConfig.branch_pattern` (default `mcp/session-{date}-{hex}`) is the single source of truth for naming, already validated for allowed placeholders (`config.py:_validate_branch_pattern`). `expand_branch_pattern` (utils.py) defines the exact placeholder semantics the regex mirrors (`%Y%m%d` → 8 digits; `secrets.token_hex(4)` → 8 lowercase hex). Deriving the matcher from the same pattern keeps generation and validation consistent.
- **Alternatives considered**:
  - *Accept any valid branch name*: rejected — the user explicitly asked to enforce the env-configured convention.
  - *Require an exact placeholder re-expansion match*: impossible (`{hex}`/`{date}` are non-deterministic); regex shape-matching is the correct equivalent.

## R4 — Tool placement, tagging, and read-only behavior

- **Decision**: Add one new tool `reset_session_branch(branch: str | None = None)` in `tools/write.py`, tagged `{"session", "write"}` with `ToolAnnotations(readOnlyHint=False)`. It is mounted only when not in read-only mode (it lives in `write_mcp`, already gated in `server.py:257`). `get_session_info` (read tool) stays in `tools/session.py`.
- **Rationale**: It mutates session state and may create a branch → it is a write operation; Principle I + AGENTS.md require write tools to be tagged `"write"` and the `ReadOnlyMiddleware` blocks them under `read_only=true`. Keeping it in `write_mcp` reuses the existing composition + gating.
- **Alternatives considered**: putting it in `session.py` (read sub-app) — rejected, would expose a mutating tool in read-only mode.
