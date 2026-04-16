"""Tests for filter coercion (app.py _coerce_filters)."""

from __future__ import annotations

import pytest

from infrahub_app.app import _coerce_filters


class TestCoerceFilters:
    def test_none_returns_none(self) -> None:
        assert _coerce_filters(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _coerce_filters("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert _coerce_filters("   ") is None

    def test_dict_passthrough(self) -> None:
        d = {"name__value": "atl1"}
        assert _coerce_filters(d) is d

    def test_json_string_parsed(self) -> None:
        result = _coerce_filters('{"name__value": "atl1"}')
        assert result == {"name__value": "atl1"}

    def test_json_string_with_whitespace(self) -> None:
        result = _coerce_filters('  {"status__value": "active"}  ')
        assert result == {"status__value": "active"}

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError, match="filters must be a JSON object"):
            _coerce_filters("atl1")

    def test_non_dict_json_raises(self) -> None:
        with pytest.raises(ValueError, match="filters must be a JSON object, not list"):
            _coerce_filters("[1, 2, 3]")
