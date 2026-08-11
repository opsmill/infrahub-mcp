# Quickstart: Marketplace integration

## Enable / disable

Marketplace access is **on by default**. To turn it off (no tools registered, no outbound call):

```bash
export INFRAHUB_MCP_MARKETPLACE_ENABLED=false
```

Point at a different marketplace:

```bash
export INFRAHUB_MCP_MARKETPLACE_URL=https://marketplace.example.internal
```

## Flow from an assistant

1. **Search**: `marketplace_search(query="dcim")` → ranked catalog entries.
2. **Read**: `marketplace_get_schema(ref="opsmill/dcim")` → metadata + YAML (pin with `version="1.2.0"`).
3. **Adopt a bundle**: `marketplace_get_collection(ref="opsmill/starter")` → multi-doc YAML.
4. **Install** (write, needs non-read-only): `marketplace_install(ref="opsmill/dcim")` → loads onto the session branch; then `propose_changes(...)` for human review. The default branch is never touched automatically.

## Verify (dev)

```bash
uv sync
uv run pytest tests/unit/test_marketplace_client.py tests/unit/test_marketplace_tools.py
uv run pytest tests/integration/test_marketplace_install.py   # testcontainers Infrahub
uv run invoke format lint
```

Expected behaviours to confirm:
- Disabled config → `marketplace_*` tools absent; no HTTP made.
- Read-only mode → `marketplace_install` blocked before any marketplace request.
- Install lands on the session branch; default branch unchanged.
- Errors distinguish ref / version / content / service (SC-004).

## Before implementing FR-001 (search)

Confirm the marketplace search endpoint path & params against the live API or `opsmill/infrahub-marketplace` — the SDK CLI only downloads by known ref and does not exercise search (see research.md Decision 3).
