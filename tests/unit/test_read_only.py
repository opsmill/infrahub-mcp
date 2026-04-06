"""Tests for read-only mode enforcement via query_graphql mutation detection."""

from __future__ import annotations

from infrahub_mcp.tools.gql import _MUTATION_PATTERN


class TestMutationDetection:
    """Test the regex pattern that detects GraphQL mutations in query_graphql."""

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
        assert _MUTATION_PATTERN.match("query { mutation_log { id } }") is None

    def test_empty_string(self) -> None:
        assert _MUTATION_PATTERN.match("") is None

    def test_subscription_not_detected(self) -> None:
        assert _MUTATION_PATTERN.match("subscription { nodeUpdated { id } }") is None

    def test_mutation_with_unicode_whitespace(self) -> None:
        """Unicode non-breaking space before mutation should be caught after lstrip()."""
        query = "\u00a0mutation { createNode { id } }"
        # lstrip() removes Unicode whitespace, so the regex matches after stripping
        assert _MUTATION_PATTERN.match(query.lstrip())
