# Graph Traversal Tools + Slimmed Schema Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two read-only MCP tools (`find_paths`, `find_reachable`) wrapping the Infrahub 1.10 graph-traversal API, and slim PR #74's recursive schema expansion down to a single, non-recursive level controlled by a boolean.

**Architecture:** Traversal logic lives in a testable core module `src/infrahub_mcp/traversal.py` (node resolution, SDK calls, result shaping), with thin `@mcp.tool` wrappers in `src/infrahub_mcp/tools/traversal.py` — mirroring the existing `schema.py` ↔ `tools/schema.py` split. The schema feature keeps only one level of peer inlining; all recursion/`@ref`/cycle machinery is deleted. A boolean config toggle replaces the numeric depth setting.

**Tech Stack:** Python 3.13, FastMCP, Infrahub SDK ≥ 1.22, Pydantic 2, pytest/pytest-asyncio, TOON encoding, uv.

## Global Constraints

- **Infrahub server ≥ 1.10** and **infrahub-sdk ≥ 1.22.0** required for traversal.
- Both new tools are **read-only**: `@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))`, tags `{"traversal", "retrieve"}`. They are NOT tagged `"write"`.
- Use the Infrahub SDK for all Infrahub access (never raw HTTP).
- Full type annotations on all new/changed code; `ruff` and `mypy` clean (`uv run invoke format lint`).
- Public functions/classes get docstrings; raise specific exceptions (no bare `except`).
- Tests are atomic, parametrized (no loops), imports at top; mock the SDK — these unit tests must NOT require a live Infrahub (unlike `tests/unit/test_tools.py`, which runs against a live instance in CI).
- HFID string format is `Kind__part1__part2` joined with `__` (`infrahub_sdk` `HFID_STR_SEPARATOR`).
- PR #74 is unmerged, so `INFRAHUB_MCP_MAX_QUERY_DEPTH` was never released — renaming config / changing tool params is NOT a breaking change; no deprecation shims.
- Run `uv sync && uv run pre-commit run && uv run pytest` before committing; docs changes also run `uv run rumdl check docs/docs/`.

---

### Task 1: Raise the SDK floor to 1.22

**Files:**
- Modify: `pyproject.toml` (the `infrahub-sdk>=1.13.5` dependency line)

**Interfaces:**
- Produces: an environment where `infrahub_sdk.graph_traversal` and `client.traverse_paths` / `client.reachable_nodes` are importable/callable.

- [ ] **Step 1: Bump the dependency**

In `pyproject.toml`, change the dependency line:

```toml
    "infrahub-sdk>=1.22.0",
```

(was `"infrahub-sdk>=1.13.5"`).

- [ ] **Step 2: Sync the environment**

Run: `uv sync`
Expected: resolves and installs `infrahub-sdk` 1.22.0 or newer; updates `uv.lock`.

- [ ] **Step 3: Verify the traversal API is importable**

Run: `uv run python -c "import infrahub_sdk; from infrahub_sdk.graph_traversal import PathTraversalResult, ReachableNodesResult; print(infrahub_sdk.__version__)"`
Expected: prints a version `>= 1.22.0`, no ImportError.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: require infrahub-sdk>=1.22.0 for graph traversal"
```

---

### Task 2: Replace numeric depth config with a boolean toggle

**Files:**
- Modify: `src/infrahub_mcp/config.py` (full rewrite of the dataclass + loader)
- Test: `tests/unit/test_config.py` (full rewrite)

**Interfaces:**
- Produces: `ServerConfig(schema_expand_peers: bool = True)`; `load_config()` reads env `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS`. Consumed by Tasks 4 (tool + resource).

- [ ] **Step 1: Rewrite the config tests**

Replace the entire contents of `tests/unit/test_config.py`:

```python
"""Tests for server configuration loading."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from infrahub_mcp.config import ServerConfig, load_config


def test_defaults() -> None:
    config = ServerConfig()
    assert config.schema_expand_peers is True


def test_frozen() -> None:
    config = ServerConfig()
    with pytest.raises(AttributeError):
        config.schema_expand_peers = False  # type: ignore[misc]


def test_load_defaults_no_env() -> None:
    with patch.dict(os.environ, {}, clear=True):
        config = load_config()
    assert config.schema_expand_peers is True


@pytest.mark.parametrize("raw", ["false", "False", "0", "no", "NO"])
def test_expand_peers_disabled(raw: str) -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_SCHEMA_EXPAND_PEERS": raw}, clear=True):
        config = load_config()
    assert config.schema_expand_peers is False


@pytest.mark.parametrize("raw", ["true", "True", "1", "yes", "YES"])
def test_expand_peers_enabled(raw: str) -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_SCHEMA_EXPAND_PEERS": raw}, clear=True):
        config = load_config()
    assert config.schema_expand_peers is True


def test_expand_peers_invalid_string() -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_SCHEMA_EXPAND_PEERS": "maybe"}, clear=True):
        with pytest.raises(ValueError, match="must be a boolean"):
            load_config()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -q`
Expected: FAIL — `ServerConfig` has no `schema_expand_peers` / import or attribute errors.

- [ ] **Step 3: Rewrite `config.py`**

Replace the entire contents of `src/infrahub_mcp/config.py`:

```python
"""Centralized server configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

_TRUE_VALUES = {"true", "1", "yes"}
_FALSE_VALUES = {"false", "0", "no"}


@dataclass(frozen=True)
class ServerConfig:
    """Immutable server configuration parsed from environment variables.

    Attributes:
        schema_expand_peers: When ``True``, schema detail responses inline one
            level of related peer schemas. When ``False``, relationships are
            returned as flat peer references.
    """

    schema_expand_peers: bool = True


def load_config() -> ServerConfig:
    """Load server configuration from environment variables.

    Environment variables:
        INFRAHUB_MCP_SCHEMA_EXPAND_PEERS: Inline one level of peer schemas in
            schema responses (default ``true``).
    """
    return ServerConfig(
        schema_expand_peers=_parse_bool("INFRAHUB_MCP_SCHEMA_EXPAND_PEERS", default=True),
    )


def _parse_bool(env_var: str, *, default: bool) -> bool:
    """Parse a boolean environment variable with a default."""
    raw = os.environ.get(env_var)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    msg = f"{env_var} must be a boolean (true/false/1/0/yes/no), got {raw!r}."
    raise ValueError(msg)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -q`
Expected: PASS (all parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add src/infrahub_mcp/config.py tests/unit/test_config.py
git commit -m "feat: replace INFRAHUB_MCP_MAX_QUERY_DEPTH with boolean INFRAHUB_MCP_SCHEMA_EXPAND_PEERS"
```

---

### Task 3: Slim `get_schema_detail` to a single non-recursive level

**Files:**
- Modify: `src/infrahub_mcp/schema.py` (rewrite `get_schema_detail`, delete `_expand_peer_schemas`, keep `_peer_rel_filters`)
- Create: `tests/unit/test_schema_expand.py`
- Delete: `tests/unit/test_schema_depth.py`

**Interfaces:**
- Consumes: `_peer_rel_filters(relationships, peer_schemas)` (unchanged), `schema_attribute_type_mapping` (unchanged).
- Produces: `get_schema_detail(client, kind, branch=None, expand_peers=True) -> dict`. Consumed by Task 4. Return dict keys: `kind, label, namespace, attributes, relationships, filters`. Each relationship: `{name, peer, cardinality, optional}` plus `peer_schema` (a dict with `kind, label, namespace, attributes, relationships` — no `filters`, and its relationships have no nested `peer_schema`) when `expand_peers` and the peer kind exists.

- [ ] **Step 1: Write the new test file**

Create `tests/unit/test_schema_expand.py`:

```python
"""Tests for single-level schema peer expansion."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from infrahub_sdk.exceptions import SchemaNotFoundError

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


def _make_schema_node(
    kind: str, label: str, namespace: str, attributes: list[Any], relationships: list[Any]
) -> MagicMock:
    node = MagicMock()
    node.kind = kind
    node.label = label
    node.namespace = namespace
    node.attributes = attributes
    node.relationships = relationships
    return node


def _make_client(schemas: dict[str, MagicMock]) -> AsyncMock:
    client = AsyncMock()

    def _get_schema(kind: str, branch: str | None = None) -> MagicMock:  # noqa: ARG001
        if kind not in schemas:
            raise SchemaNotFoundError(kind)
        return schemas[kind]

    client.schema.get = AsyncMock(side_effect=_get_schema)
    return client


def _schemas_a_b() -> dict[str, MagicMock]:
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
    return {"KindA": schema_a, "KindB": schema_b}


async def test_no_peer_schema_when_disabled() -> None:
    result = await get_schema_detail(_make_client(_schemas_a_b()), kind="KindA", expand_peers=False)
    assert result["kind"] == "KindA"
    assert "filters" in result
    for rel in result["relationships"]:
        assert "peer_schema" not in rel


async def test_peer_schema_present_when_enabled() -> None:
    result = await get_schema_detail(_make_client(_schemas_a_b()), kind="KindA", expand_peers=True)
    children = next(r for r in result["relationships"] if r["name"] == "children")
    assert children["peer_schema"]["kind"] == "KindB"
    assert "attributes" in children["peer_schema"]
    assert "relationships" in children["peer_schema"]
    assert "filters" not in children["peer_schema"]


async def test_peer_schema_relationships_not_expanded() -> None:
    result = await get_schema_detail(_make_client(_schemas_a_b()), kind="KindA", expand_peers=True)
    children = next(r for r in result["relationships"] if r["name"] == "children")
    for rel in children["peer_schema"]["relationships"]:
        assert "peer_schema" not in rel


async def test_self_referential_kind_expands_one_level() -> None:
    schema_a = _make_schema_node(
        kind="KindA",
        label="Kind A",
        namespace="Test",
        attributes=[_make_attribute("name")],
        relationships=[_make_relationship("parent", "KindA")],
    )
    result = await get_schema_detail(_make_client({"KindA": schema_a}), kind="KindA", expand_peers=True)
    parent = next(r for r in result["relationships"] if r["name"] == "parent")
    assert parent["peer_schema"]["kind"] == "KindA"
    for rel in parent["peer_schema"]["relationships"]:
        assert "peer_schema" not in rel


async def test_missing_peer_kind_skipped() -> None:
    schema_a = _make_schema_node(
        kind="KindA",
        label="Kind A",
        namespace="Test",
        attributes=[_make_attribute("name")],
        relationships=[_make_relationship("broken", "NonExistent")],
    )
    result = await get_schema_detail(_make_client({"KindA": schema_a}), kind="KindA", expand_peers=True)
    broken = next(r for r in result["relationships"] if r["name"] == "broken")
    assert broken["peer"] == "NonExistent"
    assert broken["cardinality"] == "many"
    assert broken["optional"] is False
    assert "peer_schema" not in broken


async def test_filters_include_peer_attributes() -> None:
    result = await get_schema_detail(_make_client(_schemas_a_b()), kind="KindA", expand_peers=True)
    filters = {f["filter"] for f in result["filters"]}
    assert "name__value" in filters
    assert "children__label__value" in filters
```

- [ ] **Step 2: Delete the old test file**

```bash
git rm tests/unit/test_schema_depth.py
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `uv run pytest tests/unit/test_schema_expand.py -q`
Expected: FAIL — `get_schema_detail` still has the old `depth` signature; `expand_peers` is rejected as an unexpected keyword.

- [ ] **Step 4: Rewrite `get_schema_detail` in `schema.py`**

In `src/infrahub_mcp/schema.py`: **delete** the entire `_expand_peer_schemas` function, and replace the entire `get_schema_detail` function with the version below. Keep `_peer_rel_filters`, `get_schema_catalog`, and `get_valid_kinds_summary` unchanged. The `asyncio` and `SchemaNotFoundError` imports stay.

```python
def _build_peer_schema(peer: Any) -> dict[str, Any]:
    """Build a one-level peer schema dict (no filters, no nested expansion)."""
    return {
        "kind": peer.kind,
        "label": peer.label,
        "namespace": peer.namespace,
        "attributes": [{"name": a.name, "kind": a.kind, "optional": a.optional} for a in peer.attributes],
        "relationships": [
            {"name": r.name, "peer": r.peer, "cardinality": r.cardinality, "optional": r.optional}
            for r in peer.relationships
        ],
    }


async def get_schema_detail(
    client: "InfrahubClient",
    kind: str,
    branch: str | None = None,
    expand_peers: bool = True,
) -> dict[str, Any]:
    """Return full schema detail for a specific kind.

    Includes attributes, relationships, and the complete filter map (with
    filters derived from related peer schemas fetched in parallel).

    When ``expand_peers`` is ``True``, each relationship whose peer kind exists
    includes a ``peer_schema`` key holding that peer's attributes and
    relationships, inlined a single level deep. Peer schemas omit filters and
    are not expanded further (their relationships are plain peer references).

    Args:
        client: Infrahub SDK client.
        kind: Schema kind to retrieve.
        branch: Optional branch to query.
        expand_peers: Inline one level of peer schemas on relationships.

    Returns:
        Dict with keys: kind, label, namespace, attributes, relationships, filters.

    Raises:
        SchemaNotFoundError: If the kind does not exist.
    """
    schema = await client.schema.get(kind=kind, branch=branch)

    unique_peer_kinds: list[str] = list(dict.fromkeys(rel.peer for rel in schema.relationships))

    async def _fetch_peer(peer_kind: str) -> tuple[str, Any]:
        try:
            return peer_kind, await client.schema.get(kind=peer_kind, branch=branch)
        except SchemaNotFoundError:
            return peer_kind, None

    peer_results = await asyncio.gather(*[_fetch_peer(pk) for pk in unique_peer_kinds])
    peer_schemas: dict[str, Any] = {pk: s for pk, s in peer_results if s is not None}

    filter_list: list[dict[str, str]] = [
        {
            "filter": f"{attr.name}__value",
            "type": schema_attribute_type_mapping.get(attr.kind, "String"),
        }
        for attr in schema.attributes
    ]
    filter_list.extend(_peer_rel_filters(schema.relationships, peer_schemas))

    relationships: list[dict[str, Any]] = []
    for rel in schema.relationships:
        rel_dict: dict[str, Any] = {
            "name": rel.name,
            "peer": rel.peer,
            "cardinality": rel.cardinality,
            "optional": rel.optional,
        }
        if expand_peers and rel.peer in peer_schemas:
            rel_dict["peer_schema"] = _build_peer_schema(peer_schemas[rel.peer])
        relationships.append(rel_dict)

    return {
        "kind": schema.kind,
        "label": schema.label,
        "namespace": schema.namespace,
        "attributes": [{"name": a.name, "kind": a.kind, "optional": a.optional} for a in schema.attributes],
        "relationships": relationships,
        "filters": filter_list,
    }
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `uv run pytest tests/unit/test_schema_expand.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/infrahub_mcp/schema.py tests/unit/test_schema_expand.py
git rm tests/unit/test_schema_depth.py
git commit -m "refactor: collapse schema expansion to a single non-recursive level"
```

---

### Task 4: Wire `get_schema` tool and schema resource to the boolean toggle

**Files:**
- Modify: `src/infrahub_mcp/tools/schema.py` (replace the `depth` param with `expand`)
- Modify: `src/infrahub_mcp/resources/schema.py` (use `config.schema_expand_peers`; update the resource description)

**Interfaces:**
- Consumes: `get_schema_detail(..., expand_peers=...)` (Task 3); `ServerConfig.schema_expand_peers`, `get_config` (Task 2).
- Produces: `get_schema(kind=None, branch=None, expand=None)` tool; `infrahub://schema/{kind}` resource honoring the toggle.

> Note: the tool/resource layers are exercised by the **live** integration tests in
> `tests/unit/test_tools.py` (`test_get_schema_tool_kind_detail`, `test_schema_kind_resource`,
> `test_get_schema_tool_matches_resource`), which require a running Infrahub and run in CI.
> Those tests do not pass `depth`/`expand`, so they remain valid. Do not add new live tests
> here. Local verification for this task is lint + mypy (Step 4); the live suite runs in CI.

- [ ] **Step 1: Update the `get_schema` tool**

In `src/infrahub_mcp/tools/schema.py`, replace the `depth` parameter and its handling. The new signature drops `depth` and adds `expand`:

```python
    expand: Annotated[
        bool | None,
        Field(
            default=None,
            description=(
                "Inline one level of each relationship's peer schema. "
                "Defaults to the server's INFRAHUB_MCP_SCHEMA_EXPAND_PEERS setting when omitted."
            ),
        ),
    ] = None,
```

Replace the depth-resolution block (the `resolved_depth = 0 ...` lines and the `ToolError` for negative depth) with:

```python
    config = get_config(ctx)
    expand_peers = config.schema_expand_peers if expand is None else expand
```

And change the `get_schema_detail` call from `depth=resolved_depth` to `expand_peers=expand_peers`. Update the docstring `Args:`/summary line that mentioned `depth` to describe `expand`. The `ToolError` import is no longer needed for depth — remove it only if it is otherwise unused in the file (check; `_log_and_raise_error` is still used for SchemaNotFoundError).

- [ ] **Step 2: Update the schema resource**

In `src/infrahub_mcp/resources/schema.py`:
- Change the `schema_kind_detail` call from `depth=config.max_query_depth` to `expand_peers=config.schema_expand_peers`.
- Update the `infrahub://schema/{kind}` resource `description` text: replace the sentence
  "Relationships include nested peer schemas up to the server's configured INFRAHUB_MCP_MAX_QUERY_DEPTH (default 2)."
  with
  "Relationships include one level of inlined peer schemas when INFRAHUB_MCP_SCHEMA_EXPAND_PEERS is enabled (the default)."

- [ ] **Step 3: Grep for any remaining `max_query_depth` / `depth=` references**

Run: `uv run python -c "import infrahub_mcp.tools.schema, infrahub_mcp.resources.schema, infrahub_mcp.server"`
Expected: imports succeed (no references to removed symbols).
Run: `grep -rn "max_query_depth\|MAX_QUERY_DEPTH\|depth=" src/infrahub_mcp/`
Expected: no matches.

- [ ] **Step 4: Lint and type-check**

Run: `uv run invoke format lint-ruff lint-mypy`
Expected: clean (no errors).

- [ ] **Step 5: Commit**

```bash
git add src/infrahub_mcp/tools/schema.py src/infrahub_mcp/resources/schema.py
git commit -m "feat: drive get_schema expansion from INFRAHUB_MCP_SCHEMA_EXPAND_PEERS"
```

---

### Task 5: Traversal core module (resolution, shaping, orchestrators)

**Files:**
- Create: `src/infrahub_mcp/traversal.py`
- Create: `tests/unit/test_traversal.py`

**Interfaces:**
- Consumes: `client.get(kind=, hfid=, branch=)`, `client.traverse_paths(source, destination, *, max_depth, kind_filter, relationship_filter, branch)`, `client.reachable_nodes(source, target_kinds, *, max_depth, max_results, shortest_paths_only, branch)`; SDK models `PathTraversalResult`, `ReachableNodesResult`; SDK exceptions `NodeNotFoundError`, `VersionNotSupportedError`.
- Produces (consumed by Task 6):
  - `class NodeResolutionError(Exception)`
  - `async def resolve_node_ref(client, ref: str, *, branch=None) -> str | InfrahubNode`
  - `def shape_path_result(result: PathTraversalResult) -> dict[str, Any]`
  - `def shape_reachable_result(result: ReachableNodesResult) -> dict[str, Any]`
  - `async def run_find_paths(client, *, source, destination, branch=None, max_depth=None, kind_filter=None, relationship_filter=None) -> dict[str, Any]`
  - `async def run_find_reachable(client, *, source, target_kinds, branch=None, max_depth=None, max_results=20, shortest_paths_only=True) -> dict[str, Any]`

- [ ] **Step 1: Write the tests**

Create `tests/unit/test_traversal.py`:

```python
"""Tests for graph-traversal core logic (node resolution, shaping, orchestration)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from infrahub_sdk.exceptions import NodeNotFoundError, VersionNotSupportedError
from infrahub_sdk.graph_traversal import (
    Path,
    PathHop,
    PathNode,
    PathRelationship,
    PathTraversalResult,
    ReachableNode,
    ReachableNodesResult,
)

from infrahub_mcp.traversal import (
    NodeResolutionError,
    resolve_node_ref,
    run_find_paths,
    run_find_reachable,
    shape_path_result,
    shape_reachable_result,
)

UUID_A = "1891a122-8875-bae7-3866-10658751d7cc"
UUID_B = "1891a12b-27e5-fe3e-386c-1065983045b0"


def _node(node_id: str, kind: str, label: str) -> PathNode:
    return PathNode(id=node_id, kind=kind, label=kind, display_label=label, hfid=[label])


# --- resolve_node_ref ------------------------------------------------------


async def test_resolve_uuid_passthrough() -> None:
    client = AsyncMock()
    result = await resolve_node_ref(client, UUID_A)
    assert result == UUID_A
    client.get.assert_not_called()


async def test_resolve_hfid_calls_get() -> None:
    client = AsyncMock()
    sentinel = object()
    client.get = AsyncMock(return_value=sentinel)
    result = await resolve_node_ref(client, "InfraDevice__atl1-edge1", branch="main")
    assert result is sentinel
    client.get.assert_awaited_once_with(kind="InfraDevice", hfid=["atl1-edge1"], branch="main")


async def test_resolve_multi_component_hfid() -> None:
    client = AsyncMock()
    client.get = AsyncMock(return_value=object())
    await resolve_node_ref(client, "LocationRack__site1__rack-7")
    client.get.assert_awaited_once_with(kind="LocationRack", hfid=["site1", "rack-7"], branch=None)


async def test_resolve_malformed_raises() -> None:
    client = AsyncMock()
    with pytest.raises(NodeResolutionError, match="kind-qualified HFID"):
        await resolve_node_ref(client, "noseparator")


async def test_resolve_not_found_raises() -> None:
    client = AsyncMock()
    client.get = AsyncMock(side_effect=NodeNotFoundError("InfraDevice", "nope"))
    with pytest.raises(NodeResolutionError, match="Could not resolve"):
        await resolve_node_ref(client, "InfraDevice__ghost")


# --- shaping ---------------------------------------------------------------


def test_shape_path_result() -> None:
    result = PathTraversalResult(
        source=_node(UUID_A, "InfraDevice", "edge1"),
        destination=_node(UUID_B, "InfraDevice", "edge2"),
        count=1,
        paths=[
            Path(
                depth=2,
                hops=[
                    PathHop(node=_node(UUID_A, "InfraDevice", "edge1")),
                    PathHop(
                        node=_node("x", "InfraInterfaceL3", "Ethernet1"),
                        relationship=PathRelationship(
                            from_rel="interfaces",
                            from_label="interfaces",
                            to_rel="device",
                            to_label="device",
                            kind="InfraInterface",
                        ),
                    ),
                ],
            )
        ],
    )
    shaped = shape_path_result(result)
    assert shaped["count"] == 1
    assert shaped["source"] == {"id": UUID_A, "kind": "InfraDevice", "display_label": "edge1", "hfid": ["edge1"]}
    assert shaped["paths"][0]["depth"] == 2
    first_hop, second_hop = shaped["paths"][0]["hops"]
    assert first_hop == {"node": {"kind": "InfraDevice", "display_label": "edge1"}}
    assert second_hop["node"] == {"kind": "InfraInterfaceL3", "display_label": "Ethernet1"}
    assert second_hop["relationship"] == "interfaces"


def test_shape_reachable_result() -> None:
    result = ReachableNodesResult(
        source=_node(UUID_A, "InfraDevice", "edge1"),
        count=1,
        dependencies=[
            ReachableNode(
                depth=1,
                node=_node("c", "InfraCircuit", "DUFF-1"),
                path=Path(depth=1, hops=[PathHop(node=_node("c", "InfraCircuit", "DUFF-1"))]),
            )
        ],
    )
    shaped = shape_reachable_result(result)
    assert shaped["count"] == 1
    dep = shaped["dependencies"][0]
    assert dep["depth"] == 1
    assert dep["node"] == {"id": "c", "kind": "InfraCircuit", "display_label": "DUFF-1", "hfid": ["DUFF-1"]}
    assert dep["path"]["depth"] == 1


# --- orchestrators ---------------------------------------------------------


async def test_run_find_paths_resolves_and_calls_sdk() -> None:
    client = AsyncMock()
    client.traverse_paths = AsyncMock(
        return_value=PathTraversalResult(
            source=_node(UUID_A, "InfraDevice", "edge1"),
            destination=_node(UUID_B, "InfraDevice", "edge2"),
            count=0,
            paths=[],
        )
    )
    shaped = await run_find_paths(client, source=UUID_A, destination=UUID_B, max_depth=4)
    assert shaped["count"] == 0
    client.traverse_paths.assert_awaited_once_with(
        UUID_A, UUID_B, max_depth=4, kind_filter=None, relationship_filter=None, branch=None
    )


async def test_run_find_paths_version_error_propagates() -> None:
    client = AsyncMock()
    client.traverse_paths = AsyncMock(side_effect=VersionNotSupportedError("Graph path traversal", "1.10"))
    with pytest.raises(VersionNotSupportedError):
        await run_find_paths(client, source=UUID_A, destination=UUID_B)


async def test_run_find_reachable_default_max_results() -> None:
    client = AsyncMock()
    client.reachable_nodes = AsyncMock(
        return_value=ReachableNodesResult(source=_node(UUID_A, "InfraDevice", "edge1"), count=0, dependencies=[])
    )
    await run_find_reachable(client, source=UUID_A, target_kinds=["InfraCircuit"])
    client.reachable_nodes.assert_awaited_once_with(
        UUID_A, ["InfraCircuit"], max_depth=None, max_results=20, shortest_paths_only=True, branch=None
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_traversal.py -q`
Expected: FAIL — `infrahub_mcp.traversal` does not exist (ImportError).

- [ ] **Step 3: Create `src/infrahub_mcp/traversal.py`**

```python
"""Core graph-traversal logic for the Infrahub MCP server.

Wraps the SDK's traverse_paths / reachable_nodes (Infrahub 1.10+) and shapes
their results into compact dicts for MCP tool responses. Kept separate from the
thin tool wrappers in tools/traversal.py so this logic is unit-testable without
a live server.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from infrahub_sdk.exceptions import NodeNotFoundError

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient
    from infrahub_sdk.graph_traversal import (
        Path,
        PathHop,
        PathNode,
        PathTraversalResult,
        ReachableNodesResult,
    )
    from infrahub_sdk.node import InfrahubNode

# Matches infrahub_sdk's get_human_friendly_id_as_string(include_kind=True) output.
_HFID_SEPARATOR = "__"


class NodeResolutionError(Exception):
    """Raised when a source/destination reference cannot be resolved to a node."""


def _is_uuid(value: str) -> bool:
    """Return True if value parses as a UUID (an Infrahub node id)."""
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


async def resolve_node_ref(
    client: "InfrahubClient",
    ref: str,
    *,
    branch: str | None = None,
) -> "str | InfrahubNode":
    """Resolve a node reference (UUID or kind-qualified HFID) for traversal.

    A UUID is returned unchanged (the SDK accepts a UUID string directly).
    Otherwise the value is treated as a kind-qualified HFID of the form
    ``Kind__part1__part2`` (the form get_nodes emits) and resolved via the SDK.

    Args:
        client: Infrahub SDK client.
        ref: A node UUID or a kind-qualified HFID.
        branch: Optional branch to resolve against.

    Returns:
        The UUID string, or the resolved InfrahubNode.

    Raises:
        NodeResolutionError: If the value is malformed or no node matches.
    """
    if _is_uuid(ref):
        return ref
    parts = ref.split(_HFID_SEPARATOR)
    if len(parts) < 2:  # noqa: PLR2004
        msg = f"'{ref}' is neither a UUID nor a kind-qualified HFID (expected 'Kind__id')."
        raise NodeResolutionError(msg)
    kind, hfid = parts[0], parts[1:]
    try:
        return await client.get(kind=kind, hfid=hfid, branch=branch)
    except NodeNotFoundError as exc:
        msg = f"Could not resolve '{ref}': {exc}"
        raise NodeResolutionError(msg) from exc


def _shape_node(node: "PathNode") -> dict[str, Any]:
    """Full node identity for endpoints and dependency targets."""
    return {"id": node.id, "kind": node.kind, "display_label": node.display_label, "hfid": node.hfid}


def _shape_hop(hop: "PathHop") -> dict[str, Any]:
    """Compact per-hop shape: peer identity plus the relationship name used."""
    out: dict[str, Any] = {"node": {"kind": hop.node.kind, "display_label": hop.node.display_label}}
    if hop.relationship is not None:
        out["relationship"] = hop.relationship.from_label
    return out


def _shape_path(path: "Path") -> dict[str, Any]:
    return {"depth": path.depth, "hops": [_shape_hop(h) for h in path.hops]}


def shape_path_result(result: "PathTraversalResult") -> dict[str, Any]:
    """Shape a PathTraversalResult into a compact, TOON-friendly dict."""
    return {
        "source": _shape_node(result.source),
        "destination": _shape_node(result.destination),
        "count": result.count,
        "paths": [_shape_path(p) for p in result.paths],
    }


def shape_reachable_result(result: "ReachableNodesResult") -> dict[str, Any]:
    """Shape a ReachableNodesResult into a compact, TOON-friendly dict."""
    return {
        "source": _shape_node(result.source),
        "count": result.count,
        "dependencies": [
            {"depth": dep.depth, "node": _shape_node(dep.node), "path": _shape_path(dep.path)}
            for dep in result.dependencies
        ],
    }


async def run_find_paths(  # noqa: PLR0913
    client: "InfrahubClient",
    *,
    source: str,
    destination: str,
    branch: str | None = None,
    max_depth: int | None = None,
    kind_filter: list[str] | None = None,
    relationship_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve endpoints and find shortest path(s) between two nodes."""
    src = await resolve_node_ref(client, source, branch=branch)
    dst = await resolve_node_ref(client, destination, branch=branch)
    result = await client.traverse_paths(
        src,
        dst,
        max_depth=max_depth,
        kind_filter=kind_filter,
        relationship_filter=relationship_filter,
        branch=branch,
    )
    return shape_path_result(result)


async def run_find_reachable(
    client: "InfrahubClient",
    *,
    source: str,
    target_kinds: list[str],
    branch: str | None = None,
    max_depth: int | None = None,
    max_results: int = 20,
    shortest_paths_only: bool = True,
) -> dict[str, Any]:
    """Resolve the source and find reachable nodes of the given kinds."""
    src = await resolve_node_ref(client, source, branch=branch)
    result = await client.reachable_nodes(
        src,
        target_kinds,
        max_depth=max_depth,
        max_results=max_results,
        shortest_paths_only=shortest_paths_only,
        branch=branch,
    )
    return shape_reachable_result(result)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_traversal.py -q`
Expected: PASS.

- [ ] **Step 5: Lint and type-check**

Run: `uv run invoke format lint-ruff lint-mypy`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/infrahub_mcp/traversal.py tests/unit/test_traversal.py
git commit -m "feat: add graph-traversal core (resolution, shaping, orchestration)"
```

---

### Task 6: Traversal tool wrappers + server wiring

**Files:**
- Create: `src/infrahub_mcp/tools/traversal.py`
- Modify: `src/infrahub_mcp/server.py` (import + mount + description block)
- Modify: `tests/unit/test_traversal.py` (append tool-wrapper error/translation tests)

**Interfaces:**
- Consumes: `run_find_paths`, `run_find_reachable`, `NodeResolutionError` (Task 5); `get_client`, `_log_and_raise_error`, `AppContext` (utils); `ServerConfig` (config); `VersionNotSupportedError` (SDK).
- Produces: MCP tools `find_paths`, `find_reachable`; testable impls `_find_paths_impl`, `_find_reachable_impl`; `mcp` sub-server mounted in `server.py`.

- [ ] **Step 1: Append tool-wrapper tests to `tests/unit/test_traversal.py`**

Add these imports to the existing import block at the top of the file:

```python
from fastmcp.exceptions import ToolError

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.tools.traversal import _find_paths_impl, _find_reachable_impl
from infrahub_mcp.utils import AppContext
```

Append at the end of the file:

```python
def _make_ctx(client: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = AppContext(client=client, config=ServerConfig())
    ctx.error = AsyncMock()
    ctx.info = AsyncMock()
    return ctx


async def test_find_paths_impl_happy_returns_toon() -> None:
    import toon

    client = AsyncMock()
    client.traverse_paths = AsyncMock(
        return_value=PathTraversalResult(
            source=_node(UUID_A, "InfraDevice", "edge1"),
            destination=_node(UUID_B, "InfraDevice", "edge2"),
            count=0,
            paths=[],
        )
    )
    out = await _find_paths_impl(_make_ctx(client), UUID_A, UUID_B, None, None, None, None)
    assert toon.decode(out)["count"] == 0


async def test_find_paths_impl_version_error_raises_toolerror() -> None:
    client = AsyncMock()
    client.traverse_paths = AsyncMock(side_effect=VersionNotSupportedError("Graph path traversal", "1.10"))
    with pytest.raises(ToolError, match="1.10"):
        await _find_paths_impl(_make_ctx(client), UUID_A, UUID_B, None, None, None, None)


async def test_find_paths_impl_resolution_error_raises_toolerror() -> None:
    client = AsyncMock()
    with pytest.raises(ToolError, match="get_nodes"):
        await _find_paths_impl(_make_ctx(client), "bad-ref", UUID_B, None, None, None, None)


async def test_find_reachable_impl_resolution_error_raises_toolerror() -> None:
    client = AsyncMock()
    with pytest.raises(ToolError, match="get_nodes"):
        await _find_reachable_impl(_make_ctx(client), "bad-ref", ["InfraCircuit"], None, None, 20, True)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/unit/test_traversal.py -q`
Expected: FAIL — `infrahub_mcp.tools.traversal` does not exist.

- [ ] **Step 3: Create `src/infrahub_mcp/tools/traversal.py`**

```python
"""Graph-traversal tools for the Infrahub MCP server (requires Infrahub 1.10+)."""

from typing import Annotated

import toon
from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import VersionNotSupportedError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.traversal import NodeResolutionError, run_find_paths, run_find_reachable
from infrahub_mcp.utils import _log_and_raise_error, get_client

mcp: FastMCP = FastMCP(name="Infrahub Traversal")

_VERSION_REMEDIATION = "Graph traversal requires Infrahub 1.10 or later (infrahub-sdk >= 1.22)."
_RESOLUTION_REMEDIATION = "Use get_nodes or search_nodes to obtain a valid node id or kind-qualified HFID."


async def _find_paths_impl(  # noqa: PLR0913, PLR0917
    ctx: Context,
    source: str,
    destination: str,
    branch: str | None,
    max_depth: int | None,
    kind_filter: list[str] | None,
    relationship_filter: list[str] | None,
) -> str:
    client = get_client(ctx)
    try:
        result = await run_find_paths(
            client,
            source=source,
            destination=destination,
            branch=branch,
            max_depth=max_depth,
            kind_filter=kind_filter,
            relationship_filter=relationship_filter,
        )
    except VersionNotSupportedError as exc:
        await _log_and_raise_error(ctx=ctx, error=str(exc), remediation=_VERSION_REMEDIATION)
    except NodeResolutionError as exc:
        await _log_and_raise_error(ctx=ctx, error=str(exc), remediation=_RESOLUTION_REMEDIATION)
    return toon.encode(result)


async def _find_reachable_impl(  # noqa: PLR0913, PLR0917
    ctx: Context,
    source: str,
    target_kinds: list[str],
    branch: str | None,
    max_depth: int | None,
    max_results: int,
    shortest_paths_only: bool,
) -> str:
    client = get_client(ctx)
    try:
        result = await run_find_reachable(
            client,
            source=source,
            target_kinds=target_kinds,
            branch=branch,
            max_depth=max_depth,
            max_results=max_results,
            shortest_paths_only=shortest_paths_only,
        )
    except VersionNotSupportedError as exc:
        await _log_and_raise_error(ctx=ctx, error=str(exc), remediation=_VERSION_REMEDIATION)
    except NodeResolutionError as exc:
        await _log_and_raise_error(ctx=ctx, error=str(exc), remediation=_RESOLUTION_REMEDIATION)
    return toon.encode(result)


@mcp.tool(tags={"traversal", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def find_paths(  # noqa: PLR0913, PLR0917
    ctx: Context,
    source: Annotated[str, Field(description="Start node: a UUID or kind-qualified HFID (e.g. 'InfraDevice__atl1-edge1').")],
    destination: Annotated[str, Field(description="End node: a UUID or kind-qualified HFID.")],
    branch: Annotated[str | None, Field(default=None, description="Branch to query. Defaults to the default branch.")] = None,
    max_depth: Annotated[int | None, Field(default=None, description="Maximum relationship hops to explore.")] = None,
    kind_filter: Annotated[list[str] | None, Field(default=None, description="Only traverse through nodes of these kinds.")] = None,
    relationship_filter: Annotated[
        list[str] | None,
        Field(default=None, description="Only follow these schema relationship identifiers (e.g. 'device__interface')."),
    ] = None,
) -> str:
    """Find the shortest path(s) between two nodes in the Infrahub graph.

    Use this to answer "how are these two objects connected?". A result with
    ``count`` of 0 means no path exists within ``max_depth``. Requires Infrahub 1.10+.

    Returns:
        TOON-encoded dict: source, destination, count, and paths (each a list of hops).
    """
    return await _find_paths_impl(ctx, source, destination, branch, max_depth, kind_filter, relationship_filter)


@mcp.tool(tags={"traversal", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def find_reachable(  # noqa: PLR0913, PLR0917
    ctx: Context,
    source: Annotated[str, Field(description="Source node: a UUID or kind-qualified HFID.")],
    target_kinds: Annotated[list[str], Field(description="Node kinds to search for, reachable from the source.")],
    branch: Annotated[str | None, Field(default=None, description="Branch to query. Defaults to the default branch.")] = None,
    max_depth: Annotated[int | None, Field(default=None, description="Maximum traversal depth.")] = None,
    max_results: Annotated[int, Field(default=20, description="Maximum distinct reachable nodes to return.")] = 20,
    shortest_paths_only: Annotated[bool, Field(default=True, description="Return only the shortest path to each target.")] = True,
) -> str:
    """Find nodes of the given kinds reachable from a source node (impact analysis).

    Use this to answer "what depends on / is connected to this object?" — for
    blast-radius and dependency discovery. Requires Infrahub 1.10+.

    Returns:
        TOON-encoded dict: source, count, and dependencies (each with depth, node, and path).
    """
    return await _find_reachable_impl(ctx, source, target_kinds, branch, max_depth, max_results, shortest_paths_only)
```

- [ ] **Step 4: Mount the sub-server in `server.py`**

In `src/infrahub_mcp/server.py`, add the import alongside the other tool imports (after line 15):

```python
from infrahub_mcp.tools.traversal import mcp as traversal_mcp
```

Add the mount alongside the other `mcp.mount(...)` tool calls (after `mcp.mount(schema_tools_mcp)`):

```python
mcp.mount(traversal_mcp)
```

In the server description string's "## Available tools" section, add two bullets:

```text
- **`find_paths`** — shortest path(s) between two nodes ("how are these connected?"). Requires Infrahub 1.10+.
- **`find_reachable`** — nodes of given kinds reachable from a source ("what's the blast radius?"). Requires Infrahub 1.10+.
```

Also add a one-line nudge near the tool listing: *"For 'what is connected to X' or impact analysis, prefer `find_paths`/`find_reachable` over hand-built deep GraphQL queries."*

- [ ] **Step 5: Run the traversal tests to verify they pass**

Run: `uv run pytest tests/unit/test_traversal.py -q`
Expected: PASS (core + tool-wrapper tests).

- [ ] **Step 6: Verify the server imports and registers both tools**

Run: `uv run python -c "import asyncio; from infrahub_mcp.server import mcp; print(sorted(asyncio.run(mcp.get_tools()).keys()))"`
Expected: the printed list includes `find_paths` and `find_reachable` (alongside existing tools).
(If `get_tools()` is not the available accessor in the installed FastMCP version, instead assert no ImportError on `from infrahub_mcp.server import mcp` and rely on the live test suite.)

- [ ] **Step 7: Lint and type-check**

Run: `uv run invoke format lint-ruff lint-mypy`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/infrahub_mcp/tools/traversal.py src/infrahub_mcp/server.py tests/unit/test_traversal.py
git commit -m "feat: add find_paths and find_reachable graph-traversal tools"
```

---

### Task 7: Documentation + full verification

**Files:**
- Modify: `docs/docs/references/methods.mdx` (add traversal tools; add `expand` to get_schema)
- Possibly modify: `.vale/styles/*.txt` (new terms flagged by Vale)

**Interfaces:**
- Consumes: nothing (docs only). Closes out the feature.

- [ ] **Step 1: Add traversal tool docs**

In `docs/docs/references/methods.mdx`, after the Schema section's tools (before `## Nodes`, or in a new top-level section), add a new section matching the existing per-tool format (heading wrapped in `<!-- vale off -->` / `<!-- vale on -->`):

```markdown
## Graph traversal

Graph traversal walks the live data graph to find how objects connect. It requires Infrahub 1.10 or later. `source`/`destination` accept a node UUID or a kind-qualified HFID (for example `InfraDevice__atl1-edge1`, the form `get_nodes` returns).

<!-- vale off -->
### find_paths
<!-- vale on -->

### Capabilities

- read-only
- idempotent
- no destroy

Find the shortest path(s) between two nodes. A `count` of 0 means no path within `max_depth`.

### Parameters

- **source** (string, required): start node — UUID or kind-qualified HFID
- **destination** (string, required): end node — UUID or kind-qualified HFID
- **branch** (string): branch to read from; default is the server's default branch
- **max_depth** (integer): maximum relationship hops to explore
- **kind_filter** (array of strings): only traverse through nodes of these kinds
- **relationship_filter** (array of strings): only follow these schema relationship identifiers

<!-- vale off -->
### find_reachable
<!-- vale on -->

### Capabilities

- read-only
- idempotent
- no destroy

Find nodes of the given kinds reachable from a source node — impact and dependency analysis.

### Parameters

- **source** (string, required): source node — UUID or kind-qualified HFID
- **target_kinds** (array of strings, required): node kinds to search for
- **branch** (string): branch to read from; default is the server's default branch
- **max_depth** (integer): maximum traversal depth
- **max_results** (integer, default: 20): maximum distinct reachable nodes returned
- **shortest_paths_only** (boolean, default: true): return only the shortest path to each target
```

- [ ] **Step 2: Add the `expand` parameter to the get_schema docs**

In the `### get_schema` Parameters list in `docs/docs/references/methods.mdx`, add:

```markdown
- **expand** (boolean): inline one level of each relationship's peer schema; defaults to the server's `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS` setting
```

- [ ] **Step 3: Lint the docs**

Run: `uv run rumdl check docs/docs/`
Expected: PASS (run `uv run rumdl fmt docs/docs/` first if it reports formatting fixes).

- [ ] **Step 4: Check Vale terms (CI spell-check)**

Vale runs on docs in CI and flags unknown terms. If terms like `HFID` or `traversal` are flagged, add them to the appropriate `.vale/styles/*.txt` accept list. (Search: `grep -ri "traversal\|hfid" .vale/` to find the right file; add new lines as needed.)

Run: `git grep -l "" .vale/styles/ 2>/dev/null | head` to locate the accept lists.

- [ ] **Step 5: Full verification**

Run: `uv sync && uv run pre-commit run --all-files`
Expected: ruff + mypy clean.

Run: `uv run pytest tests/unit/test_config.py tests/unit/test_schema_expand.py tests/unit/test_traversal.py -q`
Expected: PASS (the mock unit tests — runnable without a live Infrahub).

Run (only where a live Infrahub ≥ 1.10 is configured, e.g. CI): `uv run pytest -q`
Expected: full suite PASS, including the live `tests/unit/test_tools.py` schema/resource tests.

Run: `cd docs && npm run build`
Expected: docs build succeeds.

- [ ] **Step 6: Commit**

```bash
git add docs/docs/references/methods.mdx .vale/
git commit -m "docs: document find_paths/find_reachable and get_schema expand"
```

---

## Self-Review

**1. Spec coverage:**
- New tools `find_paths` / `find_reachable` → Tasks 5–6. ✓
- UUID-or-HFID resolution → Task 5 `resolve_node_ref`. ✓
- Version gating (≥1.10 / SDK ≥1.22) → Task 1 (floor) + Task 6 (`VersionNotSupportedError` → ToolError). ✓
- Result shaping & defaults (`max_results=20`, TOON) → Task 5 shaping + Task 6 `toon.encode`. ✓
- Slim `get_schema_detail` to one level, delete recursion → Task 3. ✓
- Config rename to `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS` (boolean) → Task 2. ✓
- `get_schema` `depth`→`expand`, resource toggle → Task 4. ✓
- Tests (mock SDK, parametrized) → Tasks 2, 3, 5, 6. ✓
- Docs + server description → Tasks 6–7. ✓
- Non-goals (no extra SDK knobs, no `path_exists`) → respected (only `find_paths`/`find_reachable`, limited params). ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling"; every code step shows full code. The one judgment call (hop relationship rendered as `from_label`) is implemented concretely in `_shape_hop`. ✓

**3. Type consistency:** `resolve_node_ref`, `run_find_paths`, `run_find_reachable`, `shape_path_result`, `shape_reachable_result`, `NodeResolutionError`, `_find_paths_impl`, `_find_reachable_impl` names match between Task 5/6 definitions and their test/call sites. `get_schema_detail(..., expand_peers=...)` matches between Task 3 (def), Task 4 (callers), and Task 3 tests. `ServerConfig.schema_expand_peers` matches Task 2 (def) and Task 4 (consumer). ✓
