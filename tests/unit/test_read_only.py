"""Tests for read-only mode enforcement."""

from __future__ import annotations

import re

import pytest

from infrahub_mcp.middleware import _MUTATION_PATTERN


class TestMutationDetection:
    """Test the regex pattern that detects GraphQL mutations."""

    def test_simple_mutation(self) -> None:
        assert _MUTATION_PATTERN.match("mutation { createNode { id } }")

    def test_mutation_with_name(self) -> None:
        assert _MUTATION_PATTERN.match("mutation CreateNode { createNode { id } }")

    def test_mutation_with_leading_whitespace(self) -> None:
        assert _MUTATION_PATTERN.match("  \n  mutation { createNode { id } }")

    def test_mutation_with_leading_comment(self) -> None:
        assert _MUTATION_PATTERN.match("# This is a comment\nmutation { createNode { id } }")

    def test_mutation_with_multiple_comments(self) -> None:
        assert _MUTATION_PATTERN.match("# Comment 1\n# Comment 2\nmutation { createNode { id } }")

    def test_mutation_case_insensitive(self) -> None:
        assert _MUTATION_PATTERN.match("MUTATION { createNode { id } }")

    def test_query_not_detected(self) -> None:
        assert _MUTATION_PATTERN.match("query { allNodes { id } }") is None

    def test_query_with_mutation_in_body(self) -> None:
        # "mutation" appears in body but operation is a query
        assert _MUTATION_PATTERN.match("query { mutation_log { id } }") is None

    def test_empty_string(self) -> None:
        assert _MUTATION_PATTERN.match("") is None

    def test_subscription_not_detected(self) -> None:
        assert _MUTATION_PATTERN.match("subscription { nodeUpdated { id } }") is None
