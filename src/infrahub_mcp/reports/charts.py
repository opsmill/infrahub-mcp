"""Chart builder functions for the analytics reports module.

All functions in this module accept plain data (dicts/lists) and return
Prefab UI components. They have no dependency on infrahub_sdk.
"""

from __future__ import annotations

from typing import Any

from prefab_ui.components import DataTable, DataTableColumn, Grid, Metric
from prefab_ui.components.charts import BarChart, ChartSeries, PieChart
from prefab_ui.components.mermaid import Mermaid


def build_pie_chart(
    data: list[dict[str, Any]],
    data_key: str = "value",
    name_key: str = "name",
    **kwargs: Any,
) -> PieChart:
    """Build a PieChart from data.

    Args:
        data: List of dicts, e.g. [{"name": "active", "value": 29}]
        data_key: Key for numeric values.
        name_key: Key for category names.
        **kwargs: Extra kwargs passed to PieChart (e.g. height, show_label).

    Returns:
        A PieChart component ready to embed in a PrefabApp page.
    """
    return PieChart(data=data, data_key=data_key, name_key=name_key, **kwargs)


def build_bar_chart(
    data: list[dict[str, Any]],
    x_axis: str,
    series_keys: list[str],
    **kwargs: Any,
) -> BarChart:
    """Build a BarChart from data.

    Args:
        data: List of dicts, e.g. [{"label": "Infra", "count": 20}]
        x_axis: Key for x-axis labels.
        series_keys: Keys for data series (each becomes a ChartSeries).
        **kwargs: Extra kwargs passed to BarChart (e.g. height, stacked).

    Returns:
        A BarChart component ready to embed in a PrefabApp page.
    """
    series = [ChartSeries(data_key=key) for key in series_keys]
    return BarChart(data=data, x_axis=x_axis, series=series, **kwargs)


def build_horizontal_bar_chart(
    data: list[dict[str, Any]],
    x_axis: str,
    series_keys: list[str],
    **kwargs: Any,
) -> BarChart:
    """Build a horizontal BarChart.

    Same as build_bar_chart but with horizontal=True.

    Args:
        data: List of dicts, e.g. [{"label": "Infra", "count": 20}]
        x_axis: Key for x-axis labels.
        series_keys: Keys for data series (each becomes a ChartSeries).
        **kwargs: Extra kwargs passed to BarChart (e.g. height, stacked).

    Returns:
        A horizontal BarChart component ready to embed in a PrefabApp page.
    """
    return build_bar_chart(
        data=data, x_axis=x_axis, series_keys=series_keys, horizontal=True, **kwargs
    )


def build_mermaid_er(relationships: list[tuple[str, str, str]]) -> Mermaid:
    """Build a Mermaid ER diagram from relationships.

    Args:
        relationships: List of (source_kind, relationship_name, peer_kind) tuples.

    Returns:
        Mermaid component with erDiagram syntax using ||--o{ for all relationships.
    """
    lines = ["erDiagram"]
    for source, rel_name, peer in relationships:
        lines.append(f"    {source} ||--o{{ {peer} : {rel_name}")
    return Mermaid(chart="\n".join(lines))


def build_summary_metrics(metrics: dict[str, str | int]) -> Grid:
    """Build a Grid of Metric components.

    Args:
        metrics: Ordered dict of {label: value} pairs.

    Returns:
        A Grid with columns=len(metrics), containing one Metric per entry.
    """
    grid = Grid(columns=len(metrics))
    with grid:
        for label, value in metrics.items():
            Metric(label=label, value=str(value))
    return grid


def build_data_table(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> DataTable:
    """Build a DataTable component.

    Args:
        rows: List of row dicts.
        columns: List of (key, header) tuples.

    Returns:
        DataTable with sortable columns, paginated (page_size=10).
    """
    col_defs = [DataTableColumn(key=key, header=header, sortable=True) for key, header in columns]
    return DataTable(columns=col_defs, rows=rows, paginated=True, page_size=10)
