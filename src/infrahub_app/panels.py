"""Panel engine — config parsing, auto-detection, chart building.

This module is pure logic with no async or SDK dependencies.
It converts panel configurations into Prefab UI chart components.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from prefab_ui.components.charts import AreaChart, BarChart, ChartSeries, LineChart, PieChart

if TYPE_CHECKING:
    from prefab_ui.components.base import Component


@dataclass
class PanelConfig:
    """Configuration for a single chart panel."""

    type: str  # "pie", "bar", "line", "area", "metric", "table"
    field: str  # attribute or relationship name
    options: dict[str, Any] = field(default_factory=dict)  # type: ignore[operator]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PanelConfig:
        """Create a PanelConfig from a raw dict (user input)."""
        return cls(
            type=raw["type"],
            field=raw["field"],
            options=raw.get("options", {}),
        )


def compute_distribution(
    nodes: list[dict[str, Any]], field: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Count occurrences of each value for a field. Return sorted top-N.

    Handles both scalar values and list values (many-cardinality relationships).
    Skips None values and missing keys.
    """
    if not nodes:
        return []

    counter: Counter[str] = Counter()
    for node in nodes:
        raw = node.get(field)
        if raw is None:
            continue
        if isinstance(raw, list):
            for item in raw:
                if item is not None:
                    counter[str(item)] += 1
        else:
            counter[str(raw)] += 1

    return [{"name": name, "count": count} for name, count in counter.most_common(limit)]


# Attribute kinds that map to specific chart types
_ATTR_KIND_TO_CHART: dict[str, str] = {
    "Dropdown": "pie",
    "Boolean": "pie",
    "Number": "bar",
    "Integer": "bar",
}


def auto_detect_panels(schema: dict[str, Any]) -> list[PanelConfig]:
    """Introspect a schema and return sensible panel configs.

    Rules:
    - Dropdown/Boolean attributes -> pie chart
    - Number/Integer attributes -> bar chart
    - Text and other attributes -> skipped
    - one-cardinality relationships -> pie chart (peer distribution)
    - many-cardinality relationships -> bar chart (count distribution)
    """
    panels: list[PanelConfig] = []

    for attr in schema.get("attributes", []):
        chart_type = _ATTR_KIND_TO_CHART.get(attr["kind"])
        if chart_type:
            panels.append(PanelConfig(type=chart_type, field=attr["name"]))

    for rel in schema.get("relationships", []):
        if rel.get("cardinality") == "many":
            panels.append(PanelConfig(type="bar", field=rel["name"]))
        else:
            panels.append(PanelConfig(type="pie", field=rel["name"]))

    return panels


_PIE_MAX_SLICES = 10
_PIE_UNIQUENESS_THRESHOLD = 0.5


def refine_chart_type(
    chart_type: str,
    distribution: list[dict[str, Any]],
    total_nodes: int,
) -> str:
    """Refine a chart type based on the actual data distribution.

    Switches pie → bar when the distribution has too many unique values
    (e.g., every node has a different peer for a one-cardinality relationship).
    A pie chart with many single-count slices is unreadable.
    """
    if chart_type != "pie" or not distribution or total_nodes == 0:
        return chart_type
    unique_count = len(distribution)
    if unique_count > _PIE_MAX_SLICES or unique_count / total_nodes > _PIE_UNIQUENESS_THRESHOLD:
        return "bar"
    return chart_type


def build_panel(panel: PanelConfig, data: list[dict[str, Any]]) -> Component:
    """Build a Prefab chart component from a panel config and distribution data.

    Args:
        panel: Panel configuration specifying chart type and options.
        data: Distribution data — list of dicts with "name" and "count" keys.

    Returns:
        A Prefab Component (PieChart, BarChart, etc.).

    Raises:
        ValueError: If panel.type is not supported.
    """
    opts = panel.options

    if panel.type == "pie":
        return PieChart(data=data, data_key="count", name_key="name")  # type: ignore[call-arg]

    if panel.type == "bar":
        series_keys = opts.get("series", ["count"])
        series = [ChartSeries(data_key=key) for key in series_keys]  # type: ignore[call-arg]
        return BarChart(  # type: ignore[call-arg]
            data=data,
            x_axis="name",
            series=series,
            horizontal=opts.get("horizontal", False),
            stacked=opts.get("stacked", False),
        )

    if panel.type == "line":
        series_keys = opts.get("series", ["count"])
        series = [ChartSeries(data_key=key) for key in series_keys]  # type: ignore[call-arg]
        return LineChart(data=data, x_axis="name", series=series)  # type: ignore[call-arg]

    if panel.type == "area":
        series_keys = opts.get("series", ["count"])
        series = [ChartSeries(data_key=key) for key in series_keys]  # type: ignore[call-arg]
        return AreaChart(  # type: ignore[call-arg]
            data=data,
            x_axis="name",
            series=series,
            stacked=opts.get("stacked", False),
        )

    msg = f"Unsupported panel type: {panel.type!r}"
    raise ValueError(msg)
