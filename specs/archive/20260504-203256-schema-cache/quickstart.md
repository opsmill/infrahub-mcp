# Quickstart — Verifying the Schema Cache

**Feature**: Hash-Validated Schema Cache
**Date**: 2026-05-04

This is the operator-facing walkthrough for verifying the schema cache delivers the SLAs in `spec.md`. It assumes the feature is implemented and the server is configured for `INFRAHUB_AUTH_MODE=token-passthrough` (or `basic-passthrough`).

---

## Prerequisites

- Infrahub instance reachable at `INFRAHUB_ADDRESS`.
- A valid Infrahub API token in your client (the one the MCP-connected agent will pass).
- `curl` (for direct `/metrics` probes) and `jq` (optional, for filtering).

---

## 1. Confirm the cache is enabled

```bash
INFRAHUB_MCP_SCHEMA_CACHE_ENABLED=true \
INFRAHUB_MCP_SCHEMA_CACHE_TTL=30 \
INFRAHUB_AUTH_MODE=token-passthrough \
uv run infrahub-mcp serve
```

Server start log should include:

```
schema_cache enabled=true ttl=30 max_consecutive_failures=10 max_staleness=900
```

---

## 2. Verify cache-hit on repeat reads (US1, SC-001)

From an MCP-connected agent (or via the MCP `read_resource` test harness):

1. Read `infrahub://schema` once. Observe latency.
2. Within 30 seconds, read it again. Observe latency.

Expected: second read significantly faster (no upstream `/api/schema` call).

Verify via metrics:

```bash
curl -s http://localhost:8000/metrics | grep schema_cache
```

Expected counters:

```
schema_cache_misses 1
schema_cache_hits 1
```

---

## 3. Verify hash-validated revalidation (US2, SC-002)

1. Wait until skip-window has elapsed (>30 s past last read).
2. Read `infrahub://schema` again. Observe metrics.

Expected:

```
schema_cache_hash_matches 1   # /summary confirmed cache is current
```

No new `schema_cache_misses`.

---

## 4. Verify schema-change detection (US2)

1. With the cache warm, mutate the schema in Infrahub (add a kind, rename an attribute).
2. Wait for the skip-window to elapse.
3. Read `infrahub://schema` again.

Expected:

```
schema_cache_hash_diffs 1     # /summary returned a different hash; full refetch performed
```

The agent sees the new schema on this read.

---

## 5. Verify single-flight under burst (SC-003)

From a controlled test (parallel coroutines hitting the same cold-cache branch):

```python
import asyncio
results = await asyncio.gather(*[read_schema_resource() for _ in range(10)])
```

Expected: `schema_cache_misses` increments by exactly 1, not 10.

Inspect via metrics:

```bash
curl -s http://localhost:8000/metrics | grep schema_cache_misses
# schema_cache_misses 1
```

---

## 6. Verify graceful degradation on transient failure (US3)

1. With the cache warm, block outbound network to Infrahub (e.g. firewall rule).
2. Wait for the skip-window to elapse.
3. Read `infrahub://schema`.

Expected:
- The request succeeds (cached data returned).
- A WARN log line: `schema_cache_revalidate_failure branch=main exception=...`
- Metric: `schema_cache_revalidate_failures 1`

---

## 7. Verify circuit-break (US3, SC-005a)

Continue the outage from step 6. After 10 consecutive failed revalidations *or* 900 seconds since last success (whichever first):

Expected:
- Subsequent reads return a "schema unavailable" error to the agent.
- Metric: `schema_cache_circuit_breaks 1`
- ERROR log: `schema_cache_circuit_break branch=main threshold=consecutive_failures last_success_age_seconds=...`

After Infrahub recovers and the next revalidation succeeds:
- Counter resets, reads resume serving.

---

## 8. Verify operator override (US5)

Restart with `INFRAHUB_MCP_SCHEMA_CACHE_ENABLED=false`. Confirm metrics show no schema-cache counter activity (every read goes upstream — pre-feature baseline).

Restart with `INFRAHUB_MCP_SCHEMA_CACHE_TTL=300`. Confirm hash-revalidation only fires past the new 5-minute skip-window.

---

## 9. Steady-state hit ratio (SC-004)

After warmup, run a representative agent workload for several minutes. Compute:

```bash
hits=$(curl -s http://localhost:8000/metrics | awk '/^schema_cache_hits/ {print $2}')
misses=$(curl -s http://localhost:8000/metrics | awk '/^schema_cache_misses/ {print $2}')
matches=$(curl -s http://localhost:8000/metrics | awk '/^schema_cache_hash_matches/ {print $2}')
echo "hit ratio: $(echo "scale=2; ($hits + $matches) / ($hits + $misses + $matches)" | bc)"
```

Expected: ≥ 0.90 in steady state with no schema changes.

---

## Rollback

If the cache misbehaves in production:

1. Set `INFRAHUB_MCP_SCHEMA_CACHE_ENABLED=false` and restart the server. Behaviour reverts to pre-feature baseline.
2. File a bug report including:
   - The full set of `schema_cache_*` counters at the time of the issue.
   - The branch(es) named in WARN/ERROR log lines.
   - The configured `schema_cache_*` settings.
   - The Infrahub server version (different `/api/schema/summary` shapes across versions could surface here).

The cache-disabled path is identical to today's behaviour, so the rollback is zero-risk.
