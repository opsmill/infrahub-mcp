"""Tests for read-only mode enforcement via query_graphql mutation detection."""

from __future__ import annotations

import pytest
from graphql import OperationType
from graphql import parse as gql_parse
from graphql.error import GraphQLSyntaxError


def _contains_mutation(query: str) -> bool:
    """Return True if the GraphQL document contains a mutation operation.

    Mirrors the check in ``query_graphql`` (``gql.py``).
    """
    try:
        document = gql_parse(query)
    except GraphQLSyntaxError:
        return False
    return any(hasattr(defn, "operation") and defn.operation == OperationType.MUTATION for defn in document.definitions)


class TestMutationDetection:
    """Test GraphQL-parse-based mutation detection in query_graphql."""

    def test_simple_mutation(self) -> None:
        assert _contains_mutation("mutation { createNode { id } }")

    def test_mutation_with_name(self) -> None:
        assert _contains_mutation("mutation CreateNode { createNode { id } }")

    def test_mutation_with_leading_whitespace(self) -> None:
        assert _contains_mutation("  \n  mutation { createNode { id } }")

    def test_mutation_with_leading_comment(self) -> None:
        assert _contains_mutation("# This is a comment\nmutation { createNode { id } }")

    def test_mutation_with_multiple_comments(self) -> None:
        assert _contains_mutation("# Comment 1\n# Comment 2\nmutation { createNode { id } }")

    def test_query_not_detected(self) -> None:
        assert not _contains_mutation("query { allNodes { id } }")

    def test_query_with_mutation_in_body(self) -> None:
        assert not _contains_mutation("query { mutation_log { id } }")

    def test_empty_string(self) -> None:
        assert not _contains_mutation("")

    def test_subscription_not_detected(self) -> None:
        assert not _contains_mutation("subscription { nodeUpdated { id } }")

    def test_fragment_prefixed_mutation_blocked(self) -> None:
        """A document with a fragment followed by a mutation must be detected."""
        query = """
        fragment NodeFields on Node {
            id
            name
        }
        mutation CreateNode {
            createNode { ...NodeFields }
        }
        """
        assert _contains_mutation(query)

    def test_multiple_operations_with_mutation(self) -> None:
        """A document mixing queries and mutations detects the mutation."""
        query = """
        query GetNodes { allNodes { id } }
        mutation Delete { deleteNode(id: "1") { id } }
        """
        assert _contains_mutation(query)

    def test_invalid_syntax_not_detected(self) -> None:
        """Invalid GraphQL should not be treated as a mutation."""
        assert not _contains_mutation("{{{invalid")

    @pytest.mark.parametrize(
        "query",
        [
            "{ allNodes { id } }",
            "query { allNodes { id } }",
            "query Named { allNodes { id } }",
        ],
    )
    def test_pure_queries_pass(self, query: str) -> None:
        assert not _contains_mutation(query)
