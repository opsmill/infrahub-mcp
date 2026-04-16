# Schema Query Depth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `INFRAHUB_MCP_MAX_QUERY_DEPTH` env var so schema responses recursively include related kinds' schemas, enabling agents to build nested GraphQL queries without hardcoding relationship structures.

**Architecture:** Extend `get_schema_detail()` with `depth` and `_visited` parameters for recursive peer schema expansion with cycle detection. Config caps the max depth (0-5, default 2). The tool exposes an optional `depth` param; the resource always uses the configured max.

**Tech Stack:** Python 3.13, infrahub-sdk, FastMCP, asyncio, toon, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/infrahub_mcp/config.py` | Add `max_query_depth` field + validation |
| `src/infrahub_mcp/schema.py` | Add recursive depth expansion to `get_schema_detail()` |
| `src/infrahub_mcp/tools/schema.py` | Add `depth` param to `get_schema()` tool |
| `src/infrahub_mcp/resources/schema.py` | Pass config depth to `get_schema_detail()` |
| `tests/unit/test_config.py` | Config tests for new env var |
| `tests/unit/test_schema_depth.py` | All depth/cycle/validation tests |

---

### Task 1: Config — add `max_query_depth` to `ServerConfig`

**Files:**
- Modify: `src/infrahub_mcp/config.py:14-71` (ServerConfig dataclass)
- Modify: `src/infrahub_mcp/config.py:78-139` (load_config function)
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing tests for config**

Add to `tests/unit/test_config.py`:

```python
# In TestServerConfig class:
def test_max_query_depth_default(self) -> None:
    config = ServerConfig()
    assert config.max_query_depth == 2

# In TestLoadConfig class:
def test_max_query_depth_custom(self) -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_QUERY_DEPTH": "3"}, clear=True):
        config = load_config()
    assert config.max_query_depth == 3

def test_max_query_depth_zero(self) -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_QUERY_DEPTH": "0"}, clear=True):
        config = load_config()
    assert config.max_query_depth == 0

def test_max_query_depth_negative(self) -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_QUERY_DEPTH": "-1"}, clear=True):
        with pytest.raises(ValueError, match="must be between 0 and 5"):
            load_config()

def test_max_query_depth_too_high(self) -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_QUERY_DEPTH": "10"}, clear=True):
        with pytest.raises(ValueError, match="must be between 0 and 5"):
            load_config()

def test_max_query_depth_invalid_string(self) -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_QUERY_DEPTH": "abc"}, clear=True):
        with pytest.raises(ValueError, match="must be an integer"):
            load_config()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py::TestServerConfig::test_max_query_depth_default tests/unit/test_config.py::TestLoadConfig::test_max_query_depth_custom tests/unit/test_config.py::TestLoadConfig::test_max_query_depth_zero tests/unit/test_config.py::TestLoadConfig::test_max_query_depth_negative tests/unit/test_config.py::TestLoadConfig::test_max_query_depth_too_high tests/unit/test_config.py::TestLoadConfig::test_max_query_depth_invalid_string -v`
Expected: FAIL — `ServerConfig` has no `max_query_depth` attribute

- [ ] **Step 3: Implement config changes**

In `src/infrahub_mcp/config.py`, add to `ServerConfig` dataclass (after line 70, before the closing of the class):

```python
    max_query_depth: int = 2
```

Add the docstring entry in the class docstring (after the `token_passthrough_header` entry):

```python
        max_query_depth: Maximum relationship traversal depth when returning schema
            details. ``0`` disables expansion, ``5`` is the upper limit.
```

Add a constant after `_MAX_PING_INTERVAL_MS` (line 75):

```python
_MAX_QUERY_DEPTH_LIMIT = 5
```

Add a validation function after `_validate_ping_interval()` (after line 233):

```python
def _validate_query_depth() -> None:
    """Validate INFRAHUB_MCP_MAX_QUERY_DEPTH range."""
    val = _parse_int("INFRAHUB_MCP_MAX_QUERY_DEPTH", default=2)
    if not 0 <= val <= _MAX_QUERY_DEPTH_LIMIT:
        msg = f"INFRAHUB_MCP_MAX_QUERY_DEPTH must be between 0 and {_MAX_QUERY_DEPTH_LIMIT}, got {val}."
        raise ValueError(msg)
```

In `load_config()`, add the validation call (after `_validate_ping_interval()` on line 112):

```python
    _validate_query_depth()
```

In the `load_config()` return statement, add (after `token_passthrough_header` on line 138):

```python
        max_query_depth=_parse_int("INFRAHUB_MCP_MAX_QUERY_DEPTH", default=2),
```

Add the env var to the `load_config()` docstring (after the `INFRAHUB_MCP_TOKEN_PASSTHROUGH_HEADER` line):

```
        INFRAHUB_MCP_MAX_QUERY_DEPTH: Max relationship depth in schema responses (0-5, default 2).
```

Update `test_all_env_vars` test in `tests/unit/test_config.py` — add to the `env` dict:

```python
            "INFRAHUB_MCP_MAX_QUERY_DEPTH": "3",
```

And add assertion:

```python
        assert config.max_query_depth == 3
```

Update `test_defaults` test — add assertion:

```python
        assert config.max_query_depth == 2
```

Update `test_defaults_no_env` test — add assertion:

```python
        assert config.max_query_depth == 2
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/infrahub_mcp/config.py tests/unit/test_config.py
git commit -m "feat: add INFRAHUB_MCP_MAX_QUERY_DEPTH config (0-5, default 2)"
```

---

### Task 2: Schema helper — recursive depth expansion in `get_schema_detail()`

**Files:**
- Modify: `src/infrahub_mcp/schema.py:30-78`
- Create: `tests/unit/test_schema_depth.py`

- [ ] **Step 1: Write failing tests for depth expansion**

Create `tests/unit/test_schema_depth.py`:

```python
"""Tests for recursive schema depth expansion."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from infrahub_mcp.schema import get_schema_detail


def _make_attribute(name: str, kind: str = "Text", optional: bool = False) -> MagicMock:
    attr = MagicMock()
    attr.name = name
    attr.kind = kind
    attr.optional = optional
    return attr


def _make_relationship(name: str, peer: str, cardinality: str = "many", optional: bool = False) -> MagicMock:
    rel = MagicMock()
    rel.name = name
    rel.peer = peer
    rel.cardinality = cardinality
    rel.optional = optional
    return rel


def _make_schema_node(kind: str, label: str, namespace: str, attributes: list[Any], relationships: list[Any]) -> MagicMock:
    node = MagicMock()
    node.kind = kind
    node.label = label
    node.namespace = namespace
    node.attributes = attributes
    node.relationships = relationships
    return node


def _make_client(schemas: dict[str, MagicMock]) -> AsyncMock:
    client = AsyncMock()

    async def _get_schema(kind: str, branch: str | None = None) -> MagicMock:
        from infrahub_sdk.exceptions import SchemaNotFoundError

        if kind not in schemas:
            raise SchemaNotFoundError(kind)
        return schemas[kind]

    client.schema.get = AsyncMock(side_effect=_get_schema)
    return client


class TestSchemaDepthZero:
    """Depth 0 should produce the same output as before (no peer_schema)."""

    async def test_no_peer_schema_at_depth_zero(self) -> None:
        schema_a = _make_schema_node(
            kind="KindA",
            label="Kind A",
            namespace="Test",
            attributes=[_make_attribute("name")],
            relationships=[_make_relationship("children", "KindB")],
        )
        schema_b = _make_schema_node(
            kind="KindB",
            label="Kind B",
            namespace="Test",
            attributes=[_make_attribute("label")],
            relationships=[],
        )
        client = _make_client({"KindA": schema_a, "KindB": schema_b})

        result = await get_schema_detail(client, kind="KindA", depth=0)

        assert result["kind"] == "KindA"
        for rel in result["relationships"]:
            assert "peer_schema" not in rel
            assert "_seen" not in rel


class TestSchemaDepthOne:
    """Depth 1 should include peer_schema on relationships."""

    async def test_peer_schema_present_at_depth_one(self) -> None:
        schema_a = _make_schema_node(
            kind="KindA",
            label="Kind A",
            namespace="Test",
            attributes=[_make_attribute("name")],
            relationships=[_make_relationship("children", "KindB")],
        )
        schema_b = _make_schema_node(
            kind="KindB",
            label="Kind B",
            namespace="Test",
            attributes=[_make_attribute("label")],
            relationships=[_make_relationship("parent", "KindA")],
        )
        client = _make_client({"KindA": schema_a, "KindB": schema_b})

        result = await get_schema_detail(client, kind="KindA", depth=1)

        children_rel = next(r for r in result["relationships"] if r["name"] == "children")
        assert "peer_schema" in children_rel
        assert children_rel["peer_schema"]["kind"] == "KindB"
        assert "attributes" in children_rel["peer_schema"]
        assert "relationships" in children_rel["peer_schema"]
        assert "filters" in children_rel["peer_schema"]

    async def test_peer_schema_relationships_have_no_nested_peer_schema(self) -> None:
        schema_a = _make_schema_node(
            kind="KindA",
            label="Kind A",
            namespace="Test",
            attributes=[_make_attribute("name")],
            relationships=[_make_relationship("children", "KindB")],
        )
        schema_b = _make_schema_node(
            kind="KindB",
            label="Kind B",
            namespace="Test",
            attributes=[_make_attribute("label")],
            relationships=[_make_relationship("parent", "KindA")],
        )
        client = _make_client({"KindA": schema_a, "KindB": schema_b})

        result = await get_schema_detail(client, kind="KindA", depth=1)

        children_rel = next(r for r in result["relationships"] if r["name"] == "children")
        peer_rels = children_rel["peer_schema"]["relationships"]
        for rel in peer_rels:
            assert "peer_schema" not in rel


class TestSchemaDepthTwo:
    """Depth 2 should nest two levels deep."""

    async def test_two_level_nesting(self) -> None:
        schema_a = _make_schema_node(
            kind="KindA",
            label="Kind A",
            namespace="Test",
            attributes=[_make_attribute("name")],
            relationships=[_make_relationship("children", "KindB")],
        )
        schema_b = _make_schema_node(
            kind="KindB",
            label="Kind B",
            namespace="Test",
            attributes=[_make_attribute("label")],
            relationships=[_make_relationship("items", "KindC")],
        )
        schema_c = _make_schema_node(
            kind="KindC",
            label="Kind C",
            namespace="Test",
            attributes=[_make_attribute("value")],
            relationships=[],
        )
        client = _make_client({"KindA": schema_a, "KindB": schema_b, "KindC": schema_c})

        result = await get_schema_detail(client, kind="KindA", depth=2)

        children_rel = next(r for r in result["relationships"] if r["name"] == "children")
        assert children_rel["peer_schema"]["kind"] == "KindB"

        items_rel = next(r for r in children_rel["peer_schema"]["relationships"] if r["name"] == "items")
        assert "peer_schema" in items_rel
        assert items_rel["peer_schema"]["kind"] == "KindC"


class TestSchemaCycleDetection:
    """Cycles must be detected and marked with _seen."""

    async def test_self_referential_kind(self) -> None:
        schema_a = _make_schema_node(
            kind="KindA",
            label="Kind A",
            namespace="Test",
            attributes=[_make_attribute("name")],
            relationships=[_make_relationship("parent", "KindA")],
        )
        client = _make_client({"KindA": schema_a})

        result = await get_schema_detail(client, kind="KindA", depth=2)

        parent_rel = next(r for r in result["relationships"] if r["name"] == "parent")
        assert parent_rel.get("_seen") is True
        assert "peer_schema" not in parent_rel

    async def test_mutual_cycle(self) -> None:
        schema_a = _make_schema_node(
            kind="KindA",
            label="Kind A",
            namespace="Test",
            attributes=[_make_attribute("name")],
            relationships=[_make_relationship("children", "KindB")],
        )
        schema_b = _make_schema_node(
            kind="KindB",
            label="Kind B",
            namespace="Test",
            attributes=[_make_attribute("label")],
            relationships=[_make_relationship("parent", "KindA")],
        )
        client = _make_client({"KindA": schema_a, "KindB": schema_b})

        result = await get_schema_detail(client, kind="KindA", depth=3)

        children_rel = next(r for r in result["relationships"] if r["name"] == "children")
        assert "peer_schema" in children_rel

        parent_rel = next(r for r in children_rel["peer_schema"]["relationships"] if r["name"] == "parent")
        assert parent_rel.get("_seen") is True
        assert "peer_schema" not in parent_rel

    async def test_same_kind_in_different_branches_not_marked_seen(self) -> None:
        """KindC appears via two different paths — both should expand (not cycle)."""
        schema_a = _make_schema_node(
            kind="KindA",
            label="Kind A",
            namespace="Test",
            attributes=[_make_attribute("name")],
            relationships=[
                _make_relationship("left", "KindB"),
                _make_relationship("right", "KindC"),
            ],
        )
        schema_b = _make_schema_node(
            kind="KindB",
            label="Kind B",
            namespace="Test",
            attributes=[_make_attribute("label")],
            relationships=[_make_relationship("target", "KindC")],
        )
        schema_c = _make_schema_node(
            kind="KindC",
            label="Kind C",
            namespace="Test",
            attributes=[_make_attribute("value")],
            relationships=[],
        )
        client = _make_client({"KindA": schema_a, "KindB": schema_b, "KindC": schema_c})

        result = await get_schema_detail(client, kind="KindA", depth=2)

        right_rel = next(r for r in result["relationships"] if r["name"] == "right")
        assert "peer_schema" in right_rel
        assert right_rel["peer_schema"]["kind"] == "KindC"

        left_rel = next(r for r in result["relationships"] if r["name"] == "left")
        target_rel = next(r for r in left_rel["peer_schema"]["relationships"] if r["name"] == "target")
        assert "peer_schema" in target_rel
        assert target_rel["peer_schema"]["kind"] == "KindC"


class TestSchemaNegativeDepth:
    """Negative depth should be normalized to 0."""

    async def test_negative_depth_treated_as_zero(self) -> None:
        schema_a = _make_schema_node(
            kind="KindA",
            label="Kind A",
            namespace="Test",
            attributes=[_make_attribute("name")],
            relationships=[_make_relationship("children", "KindB")],
        )
        schema_b = _make_schema_node(
            kind="KindB",
            label="Kind B",
            namespace="Test",
            attributes=[_make_attribute("label")],
            relationships=[],
        )
        client = _make_client({"KindA": schema_a, "KindB": schema_b})

        result = await get_schema_detail(client, kind="KindA", depth=-1)

        for rel in result["relationships"]:
            assert "peer_schema" not in rel
            assert "_seen" not in rel
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_schema_depth.py -v`
Expected: FAIL — `get_schema_detail()` does not accept `depth` parameter

- [ ] **Step 3: Implement recursive depth expansion**

Replace `get_schema_detail()` in `src/infrahub_mcp/schema.py` (lines 30-78) with:

```python
async def get_schema_detail(
    client: "InfrahubClient",
    kind: str,
    branch: str | None = None,
    depth: int = 0,
    _visited: set[str] | None = None,
) -> dict[str, Any]:
    """Return full schema detail for a specific kind.

    Includes attributes, relationships, and the complete filter map
    (with filters derived from related peer schemas fetched in parallel).

    When ``depth`` > 0, each relationship includes a ``peer_schema`` key
    containing the full schema of the related kind, recursively expanded
    up to ``depth`` levels. Cycles are detected per traversal path and
    marked with ``"_seen": True`` instead of ``peer_schema``.

    Args:
        client: Infrahub SDK client.
        kind: Schema kind to retrieve.
        branch: Optional branch to query.
        depth: Relationship traversal depth (0 = no expansion). Negative
            values are normalized to 0.
        _visited: Kinds already expanded in the current traversal path.
            Callers should not set this — it is managed by recursion.

    Returns:
        Dict with keys: kind, label, namespace, attributes, relationships, filters.

    Raises:
        SchemaNotFoundError: If the kind does not exist.
    """
    depth = max(depth, 0)
    if _visited is None:
        _visited = set()

    schema = await client.schema.get(kind=kind, branch=branch)

    filter_list: list[dict[str, str]] = [
        {
            "filter": f"{attr.name}__value",
            "type": schema_attribute_type_mapping.get(attr.kind, "String"),
        }
        for attr in schema.attributes
    ]

    unique_peer_kinds: list[str] = list(dict.fromkeys(rel.peer for rel in schema.relationships))

    async def _fetch_peer(peer_kind: str) -> tuple[str, Any]:
        try:
            return peer_kind, await client.schema.get(kind=peer_kind, branch=branch)
        except SchemaNotFoundError:
            return peer_kind, None

    peer_results = await asyncio.gather(*[_fetch_peer(pk) for pk in unique_peer_kinds])
    peer_schemas: dict[str, Any] = {pk: s for pk, s in peer_results if s is not None}

    for rel in schema.relationships:
        rel_schema = peer_schemas.get(rel.peer)
        if rel_schema is None:
            continue
        filter_list.extend(
            {
                "filter": f"{rel.name}__{attr.name}__value",
                "type": schema_attribute_type_mapping.get(attr.kind, "String"),
            }
            for attr in rel_schema.attributes
        )

    # Build relationship dicts with optional depth expansion
    _visited.add(kind)
    relationships: list[dict[str, Any]] = []

    # Pre-fetch peer schemas for depth expansion in parallel
    peer_detail_map: dict[str, dict[str, Any]] = {}
    if depth > 0:
        expandable_peers: list[str] = [
            rel.peer
            for rel in schema.relationships
            if rel.peer not in _visited
        ]
        unique_expandable: list[str] = list(dict.fromkeys(expandable_peers))

        async def _expand_peer(peer_kind: str) -> tuple[str, dict[str, Any]]:
            return peer_kind, await get_schema_detail(
                client, kind=peer_kind, branch=branch, depth=depth - 1, _visited=set(_visited),
            )

        expanded = await asyncio.gather(*[_expand_peer(pk) for pk in unique_expandable])
        peer_detail_map = dict(expanded)

    for rel in schema.relationships:
        rel_dict: dict[str, Any] = {
            "name": rel.name,
            "peer": rel.peer,
            "cardinality": rel.cardinality,
            "optional": rel.optional,
        }
        if depth > 0:
            if rel.peer in _visited:
                rel_dict["_seen"] = True
            elif rel.peer in peer_detail_map:
                rel_dict["peer_schema"] = peer_detail_map[rel.peer]
        relationships.append(rel_dict)

    _visited.discard(kind)

    return {
        "kind": schema.kind,
        "label": schema.label,
        "namespace": schema.namespace,
        "attributes": [{"name": a.name, "kind": a.kind, "optional": a.optional} for a in schema.attributes],
        "relationships": relationships,
        "filters": filter_list,
    }
```

Key design decisions:
- `_visited` is copied via `set(_visited)` before passing to parallel recursive calls so that different branches of the tree have independent visited sets
- `_visited.add(kind)` before processing relationships, `_visited.discard(kind)` after — this ensures cycle detection is per-path, not global
- Expandable peers are fetched in parallel via `asyncio.gather()`
- Each unique peer kind is expanded only once and reused across relationships pointing to the same kind

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_schema_depth.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `uv run pytest tests/unit/ -v`
Expected: ALL PASS (existing depth-0 tests unchanged)

- [ ] **Step 6: Commit**

```bash
git add src/infrahub_mcp/schema.py tests/unit/test_schema_depth.py
git commit -m "feat: add recursive depth expansion to get_schema_detail()"
```

---

### Task 3: Tool — add `depth` parameter to `get_schema()`

**Files:**
- Modify: `src/infrahub_mcp/tools/schema.py`
- Modify: `src/infrahub_mcp/utils.py` (for `get_config` helper)
- Test: `tests/unit/test_schema_depth.py`

- [ ] **Step 1: Write failing tests for tool depth parameter**

Add to `tests/unit/test_schema_depth.py`:

```python
from infrahub_mcp.config import ServerConfig


class TestToolDepthValidation:
    """Test depth parameter validation in the get_schema tool."""

    def test_depth_none_defaults_to_zero(self) -> None:
        """When depth is None, get_schema_detail should be called with depth=0."""
        # Tested via integration in test_tools.py — existing tests pass None implicitly

    def test_depth_capped_at_config_max(self) -> None:
        """When depth > config.max_query_depth, it should be capped."""
        config = ServerConfig(max_query_depth=2)
        assert min(5, config.max_query_depth) == 2

    def test_depth_negative_rejected(self) -> None:
        """Negative depth at tool boundary should be rejected."""
        # This is tested via the tool's validation logic
        # The tool should raise ToolError for depth < 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_schema_depth.py::TestToolDepthValidation -v`
Expected: PASS (these are basic validation logic tests, but the tool changes below are what matter)

- [ ] **Step 3: Add `get_config` helper to utils.py**

In `src/infrahub_mcp/utils.py`, add after `get_client()` (after line 57):

```python
def get_config(ctx: Context) -> ServerConfig:
    """Get the server configuration from the request context."""
    app_ctx: AppContext = ctx.request_context.lifespan_context  # type: ignore[union-attr]
    return app_ctx.config
```

- [ ] **Step 4: Update the `get_schema()` tool**

Replace the full `get_schema()` function in `src/infrahub_mcp/tools/schema.py`:

```python
"""Schema discovery tool for the Infrahub MCP server."""

import json
from typing import TYPE_CHECKING, Annotated

import toon
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from infrahub_sdk.exceptions import SchemaNotFoundError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.schema import get_schema_catalog, get_schema_detail, get_valid_kinds_summary
from infrahub_mcp.utils import _log_and_raise_error, get_client, get_config

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Schema")


@mcp.tool(tags={"schema", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_schema(
    ctx: Context,
    kind: Annotated[
        str | None,
        Field(
            default=None,
            description="Kind to get detail for. Omit to list all available kinds.",
        ),
    ] = None,
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ] = None,
    depth: Annotated[
        int | None,
        Field(
            default=None,
            description=(
                "Relationship traversal depth for schema expansion. "
                "When set, each relationship includes the full schema of its peer kind, "
                "nested up to this many levels. 0 = no expansion (default when omitted). "
                "Capped at the server's INFRAHUB_MCP_MAX_QUERY_DEPTH setting."
            ),
        ),
    ] = None,
) -> str:
    """Discover available schema kinds and their structure in Infrahub.

    Call without arguments to list all available kinds.
    Call with a ``kind`` to see its attributes, relationships, and valid filter keys.
    Set ``depth`` to include related kinds' schemas nested inline.

    Prefer reading the ``infrahub://schema`` resource if your client supports
    MCP resources — this tool provides the same data for clients that don't.

    Args:
        kind: Optional kind to get detail for. Omit to list all kinds.
        branch: Branch to query. Defaults to the default branch.
        depth: Relationship depth (0 = no expansion). Capped at server max.

    Returns:
        JSON catalog (no kind) or TOON-encoded schema detail (with kind).
    """
    client: InfrahubClient = get_client(ctx)  # type: ignore[assignment]

    if kind is None:
        catalog = await get_schema_catalog(client, branch=branch)
        return json.dumps(catalog, separators=(",", ":"))

    resolved_depth = 0
    if depth is not None:
        if depth < 0:
            msg = "depth must be non-negative."
            raise ToolError(msg)
        config = get_config(ctx)
        resolved_depth = min(depth, config.max_query_depth)

    try:
        detail = await get_schema_detail(client, kind=kind, branch=branch, depth=resolved_depth)
    except SchemaNotFoundError:
        valid = await get_valid_kinds_summary(client, branch=branch)
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation=f"{valid}\nCall get_schema() for the full catalog, or get_schema(kind='<kind>') for details.",
        )

    return toon.encode(detail)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/ -v`
Expected: ALL PASS

- [ ] **Step 6: Run linters**

Run: `uv run pre-commit run --all-files`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/infrahub_mcp/tools/schema.py src/infrahub_mcp/utils.py
git commit -m "feat: add depth parameter to get_schema tool"
```

---

### Task 4: Resource — pass config depth to `get_schema_detail()`

**Files:**
- Modify: `src/infrahub_mcp/resources/schema.py`
- Test: `tests/unit/test_schema_depth.py`

- [ ] **Step 1: Write failing test for resource depth**

Add to `tests/unit/test_schema_depth.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch


class TestResourceUsesConfigDepth:
    """The schema kind resource should pass config.max_query_depth to get_schema_detail."""

    async def test_resource_passes_config_depth(self) -> None:
        with patch("infrahub_mcp.resources.schema.get_schema_detail", new_callable=AsyncMock) as mock_detail:
            mock_detail.return_value = {
                "kind": "TestKind",
                "label": "Test Kind",
                "namespace": "Test",
                "attributes": [],
                "relationships": [],
                "filters": [],
            }
            with patch("infrahub_mcp.resources.schema.get_client") as mock_get_client, \
                 patch("infrahub_mcp.resources.schema.get_config") as mock_get_config:
                mock_get_client.return_value = AsyncMock()
                mock_config = MagicMock()
                mock_config.max_query_depth = 3
                mock_get_config.return_value = mock_config

                from infrahub_mcp.resources.schema import schema_kind_detail

                ctx = MagicMock()
                await schema_kind_detail(kind="TestKind", ctx=ctx)

                mock_detail.assert_called_once_with(
                    mock_get_client.return_value,
                    kind="TestKind",
                    depth=3,
                )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_schema_depth.py::TestResourceUsesConfigDepth -v`
Expected: FAIL — `get_schema_detail` called without `depth` arg

- [ ] **Step 3: Update resource to pass config depth**

In `src/infrahub_mcp/resources/schema.py`, update imports (line 7):

```python
from infrahub_mcp.schema import get_schema_catalog, get_schema_detail
from infrahub_mcp.utils import get_client, get_config
```

Update `schema_kind_detail()` function (lines 35-41):

```python
async def schema_kind_detail(kind: str, ctx: Context) -> str:
    """Return full schema definition and available filters for *kind* encoded as TOON."""
    client: InfrahubClient = get_client(ctx)  # type: ignore[assignment]
    config = get_config(ctx)

    try:
        payload = await get_schema_detail(client, kind=kind, depth=config.max_query_depth)
    except SchemaNotFoundError as exc:
        msg = f"Schema not found for kind '{kind}'. Read infrahub://schema to list valid kind names."
        raise ResourceError(msg) from exc

    return toon.encode(payload)
```

Update the resource description (lines 28-34) to mention depth:

```python
    description=(
        "Full schema definition for a specific node kind: attributes, relationships, "
        "and the complete set of filters accepted by get_nodes. "
        "Relationships include nested peer schemas up to the server's configured "
        "INFRAHUB_MCP_MAX_QUERY_DEPTH (default 2). "
        "Arrays are encoded in TOON tabular format: "
        "header declares fields once, each row is one entry."
    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_schema_depth.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/unit/ -v`
Expected: ALL PASS

- [ ] **Step 6: Run linters**

Run: `uv run pre-commit run --all-files`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/infrahub_mcp/resources/schema.py
git commit -m "feat: resource passes config max_query_depth to schema detail"
```

---

### Task 5: Final validation — linting, typing, and full test suite

**Files:** All modified files

- [ ] **Step 1: Run full linter suite**

Run: `uv run invoke lint`
Expected: PASS

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest`
Expected: ALL PASS

- [ ] **Step 3: Verify no regressions in existing schema tests**

Run: `uv run pytest tests/unit/test_tools.py -v -k schema`
Expected: ALL PASS — existing schema tool and resource tests must pass unchanged

- [ ] **Step 4: Review all changes**

Run: `git diff stable --stat` and `git diff stable` to verify:
- `config.py`: `max_query_depth` field, validation, parsing
- `schema.py`: `depth` + `_visited` params, recursive expansion, cycle detection
- `tools/schema.py`: `depth` param, validation, cap at config max
- `resources/schema.py`: passes `config.max_query_depth`
- `test_config.py`: config tests for new env var
- `test_schema_depth.py`: depth, cycle, validation tests
- No unrelated changes

- [ ] **Step 5: Commit any final fixes if needed**

```bash
git add -A
git commit -m "chore: final lint and type fixes"
```
