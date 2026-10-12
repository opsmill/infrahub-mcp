# Data Model: Schema-Discovery Guidance in Every MCP Client

**Feature**: [spec.md](./spec.md) | **Date**: 2026-10-12

This feature stores no data. It adds one configuration field and one generated text, and it changes the URIs of two resources.

## ServerConfig field

| Field | Environment variable | Type | Default | Validation |
| --- | --- | --- | --- | --- |
| `resources_as_tools` | `INFRAHUB_MCP_RESOURCES_AS_TOOLS` | `bool` | `False` | pydantic-settings boolean parsing, at startup (constitution principle IV). |

Read once at import of `server.py`, like `read_only`. Changing it requires a restart.

## Server instructions text

| Attribute | Value |
| --- | --- |
| Built by | `build_instructions(*, read_only: bool, resources_as_tools: bool) -> str` |
| Inputs | `ServerConfig.read_only`, `ServerConfig.resources_as_tools` |
| Variants | four: read-only on or off, combined with resource tools on or off |
| Lifetime | Built once at startup and set on `FastMCP(instructions=...)`. |
| Used by | MCP `initialize` / `server/discover` responses; the `infrahub_agent` prompt |
| Content rules | [contracts/server-instructions.md](./contracts/server-instructions.md) |

## Schema resources

| URI pattern | Parameters | Returns | Helper |
| --- | --- | --- | --- |
| `infrahub://schema` | none | JSON map of kind to label, default branch | `get_schema_catalog(client)` |
| `infrahub://schema{?branch}` | `branch: str \| None` | JSON map of kind to label, given branch | `get_schema_catalog(client, branch=branch)` |
| `infrahub://schema/{kind}{?branch}` | `kind: str`, `branch: str \| None` | TOON kind detail | `get_schema_detail(client, kind, branch, expand_peers=config.schema_expand_peers)` |

Errors: an unknown kind or an unknown branch raises `ResourceError` with a message that names `get_schema()` as the next step.
