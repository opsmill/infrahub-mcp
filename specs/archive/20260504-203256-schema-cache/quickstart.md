# Quickstart — Verifying the Schema Cache

**Feature**: Hash-Validated Schema Cache
**Date**: 2026-05-04

This is the operator-facing walkthrough for verifying the schema cache delivers the SLAs in `spec.md`. It assumes the feature is implemented and the server is configured for `INFRAHUB_AUTH_MODE=token-passthrough` (or `basic-passthrough`).

---

## Prerequisites

- Infrahub instance reachable at `INFRAHUB_ADDRESS`.
- A valid Infrahub API token in your client (the one the MCP-connected agent will pass).
- The server running with `--transport streamable-http`; `/metrics` is only reachable over HTTP.
- `curl` (for direct `/metrics` probes), plus `awk` and `bc` for the ratio computation in step 9.

---

## 1. Confirm the cache is enabled

```bash
INFRAHUB_MCP_SCHEMA_CACHE_ENABLED=true \
INFRAHUB_MCP_SCHEMA_CACHE_TTL=30 \
INFRAHUB_MCP_PROMETHEUS_ENABLED=true \
INFRAHUB_MCP_CACHE_ENABLED=true \
INFRAHUB_MCP_AUTH_MODE=token-passthrough \
uv run infrahub-mcp --transport streamable-http --port 8000
```

`INFRAHUB_MCP_PROMETHEUS_ENABLED=true` makes `/metrics` serve Prometheus exposition text, which every probe below relies on.

There is no dedicated `schema_cache` startup log line. Read the resolved settings straight off `ServerConfig`, with the same environment exported:

```bash
uv run python -c "from infrahub_mcp.config import ServerConfig; print({k: v for k, v in ServerConfig().model_dump().items() if k.startswith('schema_cache')})"
```

```text
{'schema_cache_enabled': True, 'schema_cache_ttl': 30, 'schema_cache_max_consecutive_failures': 10, 'schema_cache_max_staleness_seconds': 900}
```

Two startup cross-checks confirm the wiring:

- Because `INFRAHUB_MCP_CACHE_ENABLED=true`, the middleware stack logs `response_caching enabled=true list_ttl=300 read_ttl=3600 schema_uris_bypassed=True`. The `schema_uris_bypassed` field echoes `schema_cache_enabled` — when it is `True`, the schema cache owns the schema URIs and `ResponseCachingMiddleware` stays out of the way.
- The six schema-cache counters are registered at process start, so they are already exposed (at zero) before the first read:

```bash
curl -s http://localhost:8000/metrics | grep '^infrahub_mcp_schema_cache'
```

```text
infrahub_mcp_schema_cache_circuit_break_total 0
infrahub_mcp_schema_cache_hash_diff_total 0
infrahub_mcp_schema_cache_hash_match_total 0
infrahub_mcp_schema_cache_hit_total 0
infrahub_mcp_schema_cache_miss_total 0
infrahub_mcp_schema_cache_revalidate_failure_total 0
```

> With `INFRAHUB_MCP_PROMETHEUS_ENABLED` unset, `/metrics` returns JSON instead and the same six counters live under a `schema_cache` object — `{"schema_cache": {"hit": 0, "miss": 0, "hash_match": 0, "hash_diff": 0, "revalidate_failure": 0, "circuit_break": 0}}`. The rest of this walkthrough assumes the Prometheus output.

---

## 2. Verify cache-hit on repeat reads (US1, SC-001)

From an MCP-connected agent (or via the MCP `read_resource` test harness):

1. Read `infrahub://schema` once. Observe latency.
2. Within 30 seconds, read it again. Observe latency.

Expected: second read significantly faster (no upstream `/api/schema` call).

Verify via metrics:

```bash
curl -s http://localhost:8000/metrics | grep '^infrahub_mcp_schema_cache'
```

Expected counters (the zeroed ones are omitted here for brevity):

```text
infrahub_mcp_schema_cache_hit_total 1
infrahub_mcp_schema_cache_miss_total 1
```

---

## 3. Verify hash-validated revalidation (US2, SC-002)

1. Wait until skip-window has elapsed (>30 s past last read).
2. Read `infrahub://schema` again. Observe metrics.

Expected:

```text
infrahub_mcp_schema_cache_hash_match_total 1   # /summary confirmed cache is current
```

No new `infrahub_mcp_schema_cache_miss_total`.

---

## 4. Verify schema-change detection (US2)

1. With the cache warm, mutate the schema in Infrahub (add a kind, rename an attribute).
2. Wait for the skip-window to elapse.
3. Read `infrahub://schema` again.

Expected:

```text
infrahub_mcp_schema_cache_hash_diff_total 1     # /summary returned a different hash; full refetch performed
```

The agent sees the new schema on this read.

---

## 5. Verify single-flight under burst (SC-003)

From a controlled test (parallel coroutines hitting the same cold-cache branch):

```python
import asyncio

results = await asyncio.gather(*[read_schema_resource() for _ in range(10)])
```

Expected: `infrahub_mcp_schema_cache_miss_total` increments by exactly 1, not 10.

Inspect via metrics:

```bash
curl -s http://localhost:8000/metrics | grep '^infrahub_mcp_schema_cache_miss_total'
# infrahub_mcp_schema_cache_miss_total 1
```

---

## 6. Verify graceful degradation on transient failure (US3)

1. With the cache warm, block outbound network to Infrahub (e.g. firewall rule).
2. Wait for the skip-window to elapse.
3. Read `infrahub://schema`.

Expected:

- The request succeeds (cached data returned).
- A WARN log line: `schema_cache_revalidate_failure branch=main exception=...`
- Metric: `infrahub_mcp_schema_cache_revalidate_failure_total 1`

---

## 7. Verify circuit-break (US3, SC-005a)

Continue the outage from step 6. After 10 consecutive failed revalidations *or* 900 seconds since last success (whichever first):

Expected:

- Subsequent reads return a "schema unavailable" error to the agent.
- Metric: `infrahub_mcp_schema_cache_circuit_break_total 1` — this counts breaker *trips*, so it increments once when the entry crosses a threshold, not once per rejected read.
- ERROR log: `schema_cache_circuit_break branch=main threshold=consecutive_failures last_success_age_seconds=...`

A tripped entry is not written off. Reads keep probing upstream — at most one probe per `schema_cache_ttl`, so an outage costs one upstream timeout per window rather than one per request — and fail closed only while those probes keep failing. Reads inside a throttle window return the same error without touching Infrahub.

After Infrahub recovers, the next probe succeeds on its own:

- The entry's `consecutive_failures` resets to 0 and reads resume serving, with no restart needed. The `circuit_break` metric is a cumulative counter, so it does not decrease.

---

## 8. Verify operator override (US5)

Restart with `INFRAHUB_MCP_SCHEMA_CACHE_ENABLED=false`. The six `infrahub_mcp_schema_cache_*_total` counters are still exported, but all of them stay at `0` no matter how many schema reads run — every read goes upstream (pre-feature baseline).

Restart with `INFRAHUB_MCP_SCHEMA_CACHE_TTL=300`. Confirm hash-revalidation only fires past the new 5-minute skip-window.

---

## 9. Steady-state hit ratio (SC-004)

After warmup, run a representative agent workload for several minutes. Compute:

```bash
metrics=$(curl -s http://localhost:8000/metrics)
counter() {
  printf '%s\n' "$metrics" |
    awk -v name="infrahub_mcp_schema_cache_$1_total" \
      '$1 == name { print $2; found = 1 } END { if (!found) print 0 }'
}

hits=$(counter hit)
misses=$(counter miss)
matches=$(counter hash_match)

served=$((hits + matches))
total=$((served + misses))
if [ "$total" -gt 0 ]; then
  echo "hit ratio: $(echo "scale=2; $served / $total" | bc)"
else
  echo "no schema reads recorded yet"
fi
```

The `$1 == name` comparison is what makes this exact: it matches only the metric line and skips the `# HELP` / `# TYPE` lines that share the same prefix.

Expected: ≥ 0.90 in steady state with no schema changes.

---

## Rollback

If the cache misbehaves in production:

1. Set `INFRAHUB_MCP_SCHEMA_CACHE_ENABLED=false` and restart the server. Behaviour reverts to pre-feature baseline.
2. File a bug report including:
   - The full set of `infrahub_mcp_schema_cache_*_total` counters at the time of the issue.
   - The branch(es) named in WARN/ERROR log lines.
   - The configured `INFRAHUB_MCP_SCHEMA_CACHE_*` settings.
   - The Infrahub server version (different `/api/schema/summary` shapes across versions could surface here).

The cache-disabled path is identical to today's behaviour, so the rollback is zero-risk.
