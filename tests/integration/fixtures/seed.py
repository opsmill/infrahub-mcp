"""Deterministic seed data for the MCP integration suite.

Loaded once per session into the ``main`` branch (research D9). Per-test
branches are created off this baseline so every test starts from a known state.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ruamel.yaml import YAML

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

SCHEMA_PATH = Path(__file__).parent / "schema_minimal.yml"

#: Kind exposed by ``schema_minimal.yml`` (namespace ``Testing`` + name ``Widget``).
WIDGET_KIND = "TestingWidget"

#: Baseline widgets created on ``main``. Two are red / one is blue so the
#: ``get_nodes`` filter case has a non-trivial result, and three rows let the
#: pagination case request a partial page.
SEED_WIDGETS: tuple[dict[str, object], ...] = (
    {"name": "alpha", "color": "red", "quantity": 1},
    {"name": "beta", "color": "blue", "quantity": 2},
    {"name": "gamma", "color": "red", "quantity": 3},
)


def _load_schema_dict() -> dict[str, object]:
    yaml = YAML(typ="safe")
    return yaml.load(SCHEMA_PATH.read_text(encoding="utf-8"))


async def load_schema(client: InfrahubClient, *, branch: str = "main") -> None:
    """Load the minimal test schema and wait for it to converge."""
    await client.schema.load(schemas=[_load_schema_dict()], branch=branch, wait_until_converged=True)


async def seed_baseline(client: InfrahubClient, *, branch: str = "main") -> dict[str, str]:
    """Load the schema and create the baseline widgets on ``branch``.

    Returns a mapping of widget name -> created node id, so tests can assert
    against known ids without rediscovering them.
    """
    await load_schema(client, branch=branch)
    created: dict[str, str] = {}
    for widget in SEED_WIDGETS:
        node = await client.create(kind=WIDGET_KIND, data=dict(widget), branch=branch)
        await node.save()
        created[str(widget["name"])] = str(node.id)
    return created
