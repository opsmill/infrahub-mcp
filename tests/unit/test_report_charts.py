"""Tests for the chart builder functions in infrahub_mcp.reports.charts."""

from __future__ import annotations

from prefab_ui.components import DataTable, Grid, Metric
from prefab_ui.components.charts import BarChart, PieChart
from prefab_ui.components.mermaid import Mermaid

from infrahub_mcp.reports.charts import (
    build_bar_chart,
    build_data_table,
    build_horizontal_bar_chart,
    build_mermaid_er,
    build_pie_chart,
    build_summary_metrics,
)


class TestBuildPieChart:
    def test_returns_pie_chart_with_correct_data_key_and_name_key(self) -> None:
        data = [{"name": "active", "value": 29}, {"name": "inactive", "value": 5}]
        chart = build_pie_chart(data, data_key="value", name_key="name")
        assert isinstance(chart, PieChart)
        assert chart.data_key == "value"
        assert chart.name_key == "name"

    def test_empty_data_produces_valid_pie_chart(self) -> None:
        chart = build_pie_chart([])
        assert isinstance(chart, PieChart)
        assert chart.data == []

    def test_kwargs_are_forwarded_to_pie_chart(self) -> None:
        chart = build_pie_chart([{"name": "x", "value": 1}], height=400, show_label=True)
        assert chart.height == 400
        assert chart.show_label is True


class TestBuildBarChart:
    def test_returns_bar_chart_with_correct_series_and_x_axis(self) -> None:
        data = [{"label": "Infra", "count": 20}]
        chart = build_bar_chart(data, x_axis="label", series_keys=["count"])
        assert isinstance(chart, BarChart)
        assert chart.x_axis == "label"
        assert len(chart.series) == 1
        assert chart.series[0].data_key == "count"

    def test_multiple_series_keys_create_multiple_chart_series(self) -> None:
        data = [{"label": "Q1", "new": 10, "deleted": 3}]
        chart = build_bar_chart(data, x_axis="label", series_keys=["new", "deleted"])
        assert len(chart.series) == 2
        assert chart.series[0].data_key == "new"
        assert chart.series[1].data_key == "deleted"

    def test_horizontal_is_false_by_default(self) -> None:
        chart = build_bar_chart([], x_axis="label", series_keys=["count"])
        assert chart.horizontal is False

    def test_kwargs_are_forwarded_to_bar_chart(self) -> None:
        chart = build_bar_chart([], x_axis="label", series_keys=["count"], stacked=True, height=500)
        assert chart.stacked is True
        assert chart.height == 500


class TestBuildHorizontalBarChart:
    def test_returns_bar_chart_with_horizontal_true(self) -> None:
        data = [{"label": "Infra", "count": 20}]
        chart = build_horizontal_bar_chart(data, x_axis="label", series_keys=["count"])
        assert isinstance(chart, BarChart)
        assert chart.horizontal is True

    def test_series_and_x_axis_are_set_correctly(self) -> None:
        data = [{"label": "Infra", "count": 20}]
        chart = build_horizontal_bar_chart(data, x_axis="label", series_keys=["count"])
        assert chart.x_axis == "label"
        assert chart.series[0].data_key == "count"


class TestBuildMermaidEr:
    def test_returns_mermaid_with_valid_er_diagram_syntax(self) -> None:
        relationships = [
            ("InfraDevice", "interfaces", "InfraInterfaceL3"),
            ("InfraDevice", "site", "LocationSite"),
        ]
        mermaid = build_mermaid_er(relationships)
        assert isinstance(mermaid, Mermaid)
        assert mermaid.chart.startswith("erDiagram")
        assert "InfraDevice ||--o{ InfraInterfaceL3 : interfaces" in mermaid.chart
        assert "InfraDevice ||--o{ LocationSite : site" in mermaid.chart

    def test_empty_relationships_returns_mermaid_with_just_er_diagram(self) -> None:
        mermaid = build_mermaid_er([])
        assert isinstance(mermaid, Mermaid)
        assert mermaid.chart == "erDiagram"


class TestBuildSummaryMetrics:
    def test_returns_grid_containing_metric_components(self) -> None:
        metrics = {"Total": 42, "Active": 30, "Inactive": 12}
        grid = build_summary_metrics(metrics)
        assert isinstance(grid, Grid)
        assert all(isinstance(child, Metric) for child in grid.children)

    def test_grid_has_correct_columns_count(self) -> None:
        metrics = {"Total": 42, "Active": 30, "Inactive": 12}
        grid = build_summary_metrics(metrics)
        assert grid.columns == 3

    def test_metric_labels_and_values_are_set(self) -> None:
        metrics = {"Total": 100, "Active": 80}
        grid = build_summary_metrics(metrics)
        labels = [child.label for child in grid.children if isinstance(child, Metric)]
        values = [child.value for child in grid.children if isinstance(child, Metric)]
        assert labels == ["Total", "Active"]
        assert values == ["100", "80"]

    def test_single_metric(self) -> None:
        grid = build_summary_metrics({"Count": "5"})
        assert grid.columns == 1
        assert len(grid.children) == 1


class TestBuildDataTable:
    def test_returns_data_table_with_correct_columns_and_data(self) -> None:
        rows = [{"name": "router-1", "status": "active"}]
        columns = [("name", "Name"), ("status", "Status")]
        table = build_data_table(rows, columns)
        assert isinstance(table, DataTable)
        assert len(table.columns) == 2
        assert table.columns[0].key == "name"
        assert table.columns[0].header == "Name"
        assert table.columns[1].key == "status"
        assert table.columns[1].header == "Status"

    def test_data_table_is_paginated_with_page_size_10(self) -> None:
        table = build_data_table([], [("id", "ID")])
        assert table.paginated is True
        assert table.page_size == 10

    def test_columns_are_sortable(self) -> None:
        columns = [("name", "Name"), ("count", "Count")]
        table = build_data_table([], columns)
        assert all(col.sortable for col in table.columns)

    def test_empty_rows_produces_valid_table(self) -> None:
        table = build_data_table([], [("id", "ID")])
        assert isinstance(table, DataTable)
        assert table.rows == []
