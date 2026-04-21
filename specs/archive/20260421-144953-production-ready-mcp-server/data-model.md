# Data Model: Production-Ready MCP Server

**Note**: Retrospective documentation of implemented entities.

## ServerConfig

Immutable configuration loaded from `INFRAHUB_MCP_*` environment variables.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| read_only | bool | false | Hide and block write tools |
| branch_pattern | str | `mcp/session-{date}-{hex}` | Session branch naming pattern |
| max_branch_retries | int (1-20) | 5 | Collision retry limit |
| log_level | str | `info` | Logging verbosity |
| rate_limit_rps | int | 0 (disabled) | Max sustained requests/sec |
| rate_limit_burst | int | 0 (auto) | Token-bucket burst capacity |
| retry_max_attempts | int | 0 (disabled) | Transient failure retries |
| retry_base_delay | float | 1.0 | Initial retry delay (seconds) |
| cache_enabled | bool | false | Response caching toggle |
| cache_list_ttl | int | — | List operation cache TTL |
| cache_read_ttl | int | — | Read operation cache TTL |
| otel_enabled | bool | false | OpenTelemetry tracing |
| prometheus_enabled | bool | false | Prometheus /metrics endpoint |
| dereference_schemas | bool | false | JSON Schema $ref resolution |
| ping_interval_ms | int | 0 (disabled) | HTTP session ping interval |
| auth_mode | AuthMode | `none` | Authentication mode |
| auth_scopes_write | str | `write` | OAuth scopes for write ops |
| oidc_config_url | str | — | OIDC discovery URL |
| oidc_client_id | str | — | OAuth client ID |
| oidc_client_secret | str | — | OAuth client secret (optional) |
| oidc_base_url | str | — | MCP server public URL |
| oidc_audience | str | — | Token audience claim |
| oidc_user_claim | str | `email` | JWT claim for user identity |
| token_passthrough_header | str | `Authorization` | Credential header name |

**Validation rules**:
- `auth_mode` is one of: `none`, `oidc`, `token-passthrough`, `basic-passthrough`
- When `auth_mode=oidc`: `oidc_config_url`, `oidc_client_id`, `oidc_base_url` are required
- `branch_pattern` only accepts `{date}`, `{hex}`, `{user}` placeholders
- `log_level` is one of: `debug`, `info`, `warning`, `error`
- Model is frozen (immutable after construction)

## AuthMode

```
Literal["none", "oidc", "token-passthrough", "basic-passthrough"]
```

**State transitions**: None — auth mode is fixed at startup.

## AppContext

Runtime context shared via FastMCP lifespan dependency injection.

| Field | Type | Description |
|-------|------|-------------|
| client | InfrahubClient ∣ None | SDK client (None in passthrough modes) |
| config | ServerConfig | Immutable server configuration |

## Session State (per-request)

Managed via `ContextVar` — no persistent entity.

| ContextVar | Type | Description |
|------------|------|-------------|
| current_request_id | str ∣ None | Unique request correlation ID |
| _passthrough_token | str ∣ None | Per-request Bearer token |
| _passthrough_basic | tuple[str, str] ∣ None | Per-request username/password |
| _session_branch | str ∣ None | Active session branch name |

## Middleware Stack

Ordered chain of interceptors. Not a data entity — a runtime composition.

**Relationships**:
- `ServerConfig` → determines which middleware layers are activated
- `AppContext` → middleware accesses config via context
- Session ContextVars → middleware reads/writes per-request state

## Entity Relationships

```
ServerConfig ─────creates────── AppContext
     │                              │
     │                              │ lifespan injection
     │                              ▼
     │                        FastMCP Server
     │                              │
     ├──activates──── Middleware Stack (17 layers)
     │                              │
     │                              │ per-request
     │                              ▼
     └──configures── Session ContextVars
                      (request_id, credentials, branch)
```
