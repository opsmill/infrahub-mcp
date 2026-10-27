# 9. Session-Branch Key Without MCP Sessions

**Status:** Accepted
**Date:** 2026-10-07
**Author:** @qduk

Supersedes the "Per-session scoping" decision in [ADR 0007](0007-per-session-branch-recovery-and-reset.md). The recovery, reset and write-authorization decisions in ADR 0007 are unchanged.

## Context

ADR 0007 stored the session branch in `WeakKeyDictionary` maps keyed by `ctx.request_context.session`. From MCP protocol version 2026-07-28, which FastMCP 4 and MCP SDK v2 use when the client supports it, the protocol has no sessions: every request gets a new `ServerSession` and a new `Connection`, and `ctx.session_id` is a new random value on each call.

As a result, the server never found the branch that a previous call stored:

- Every `node_upsert`, `node_delete` and `mutate_graphql` call created a new branch.
- `propose_changes` failed with "No session branch exists yet", so an agent could not open a proposed change.
- `get_session_info` always returned `null`.

## Decision

Key the session branch and its lock on a string returned by `_session_key()` in `utils.py`. The key joins these parts, in this order:

1. `caller:<sha256>` from `get_caller_identity()` in `auth.py`: the OIDC principal (client id, issuer, subject), else the passthrough API token, else the passthrough Basic credentials. The value is hashed so that credentials are never held as dictionary keys.
2. `session:<id>` from the `mcp-session-id` request header. Clients that use a stateful streamable-HTTP session (older protocol versions) send it, so these clients keep one branch per session.

The caller comes first because the client sets the header: a session id sent by one caller must never address another caller's branch. When neither part is present, the key is `process`: one key for the server process. With stdio, one process serves one client, so this matches one client session.

The maps are `OrderedDict`s that keep at most 1024 keys and drop the least recently used key first. A lock that is held is never dropped.

## Consequences

### Positive

- Writes in one conversation reuse one branch again, and `propose_changes` finds it, on every protocol version and transport.
- The tool API does not change.
- Memory use is bounded by the 1024-key limit instead of by session lifetime.

### Negative

- Without a session id, isolation is per caller, not per conversation. Two conversations by the same user, or with the same passthrough token, share one branch.
- Unauthenticated HTTP clients (`auth_mode=none` over streamable HTTP) that do not send a session id share the `process` branch.
- Rotating a passthrough token or password starts a new branch for that caller.
- A key that is dropped by the limit loses its branch reference. The branch still exists in Infrahub and can be selected again with `reset_session_branch`.

## Alternatives Considered

### Agent-supplied session id (FastMCP `SessionProvider`)

Add `create_session` and `end_session` tools and a `session_id` argument to every write tool, `propose_changes` and `get_session_info`. This isolates each conversation on every transport. Rejected for now because it changes the tool API and requires the agent to call `create_session` first. It remains the option if per-conversation isolation becomes a requirement.

### One branch for the whole process

The smallest change. Rejected because it removes per-user isolation for every HTTP deployment, including authenticated ones.
