"""Tests for branch pattern expansion and collision handling."""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from infrahub_mcp.utils import _has_placeholders, expand_branch_pattern


class TestHasPlaceholders:
    def test_with_date(self) -> None:
        assert _has_placeholders("mcp/session-{date}") is True

    def test_with_hex(self) -> None:
        assert _has_placeholders("mcp/{hex}") is True

    def test_with_user(self) -> None:
        assert _has_placeholders("mcp/{user}-branch") is True

    def test_with_multiple(self) -> None:
        assert _has_placeholders("mcp/{user}-{date}-{hex}") is True

    def test_fixed_name(self) -> None:
        assert _has_placeholders("staging") is False

    def test_fixed_with_braces_but_not_placeholder(self) -> None:
        assert _has_placeholders("mcp/{other}") is False

    def test_empty(self) -> None:
        assert _has_placeholders("") is False


class TestExpandBranchPattern:
    def test_default_pattern(self) -> None:
        result = expand_branch_pattern("mcp/session-{date}-{hex}")
        assert re.match(r"mcp/session-\d{8}-[0-9a-f]{8}", result)

    def test_date_only(self) -> None:
        result = expand_branch_pattern("mcp/{date}")
        assert re.match(r"mcp/\d{8}", result)

    def test_hex_only(self) -> None:
        result = expand_branch_pattern("{hex}")
        assert re.match(r"[0-9a-f]{8}", result)

    def test_user_placeholder(self) -> None:
        result = expand_branch_pattern("mcp/{user}-{date}")
        assert re.match(r"mcp/anonymous-\d{8}", result)

    def test_no_placeholders_passthrough(self) -> None:
        result = expand_branch_pattern("staging")
        assert result == "staging"

    def test_uniqueness(self) -> None:
        """Two expansions with {hex} should produce different results (with high probability)."""
        a = expand_branch_pattern("{hex}")
        b = expand_branch_pattern("{hex}")
        # Theoretically could collide but probability is 1/2^32
        assert a != b


class TestExpandBranchPatternUser:
    def test_user_placeholder_with_oidc_identity(self) -> None:
        with patch("infrahub_mcp.utils.get_user_from_token", return_value="alice-example.com"):
            result = expand_branch_pattern("mcp/{user}-{date}", user_claim="email")
        assert "alice-example.com" in result

    def test_user_placeholder_anonymous_when_no_token(self) -> None:
        with patch("infrahub_mcp.utils.get_user_from_token", return_value="anonymous"):
            result = expand_branch_pattern("mcp/{user}-{date}", user_claim="email")
        assert "anonymous" in result

    def test_user_placeholder_default_anonymous_no_claim(self) -> None:
        """Without user_claim, {user} resolves to 'anonymous' (mode=none)."""
        result = expand_branch_pattern("mcp/{user}-{date}")
        assert "anonymous" in result
