from fastmcp import Client

from infrahub_mcp.prompts.prompts import mcp

# --- answer_infra_question ---


async def test_answer_infra_question_basic() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt("answer_infra_question", arguments={"question": "How many sites exist?"})
        assert len(result.messages) == 1
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "How many sites exist?" in text
        assert "infrahub://schema" in text
        assert "get_nodes" in text
        assert "search_nodes" in text
        assert "query_graphql" in text
        assert "TOON" in text


async def test_answer_infra_question_with_kind_hint() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt(
            "answer_infra_question",
            arguments={"question": "List all sites", "kind_hint": "LocationSite"},
        )
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "LocationSite" in text
        assert "Skip catalog discovery" in text
        assert "infrahub://schema/LocationSite" in text


async def test_answer_infra_question_with_fields() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt(
            "answer_infra_question",
            arguments={"question": "Show device names", "fields": "name,status"},
        )
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "name,status" in text
        assert "include_attributes=True" in text


async def test_answer_infra_question_with_branch() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt(
            "answer_infra_question",
            arguments={"question": "What devices are on this branch?", "branch": "feature-123"},
        )
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "feature-123" in text
        assert 'branch="feature-123"' in text


async def test_answer_infra_question_all_params() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt(
            "answer_infra_question",
            arguments={
                "question": "What IPs are assigned?",
                "kind_hint": "IpamIPAddress",
                "fields": "address",
                "branch": "dev",
            },
        )
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "IpamIPAddress" in text
        assert "address" in text
        assert 'branch="dev"' in text
        assert "include_attributes=True" in text


# --- make_infra_change ---


async def test_make_infra_change_basic() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt("make_infra_change", arguments={"description": "Add a new site called lax1"})
        assert len(result.messages) == 1
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "Add a new site called lax1" in text
        assert "node_upsert" in text
        assert "node_delete" in text
        assert "propose_changes" in text
        assert "session branch" in text
        assert "infrahub://schema" in text


async def test_make_infra_change_with_kind() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt(
            "make_infra_change",
            arguments={"description": "Update site status", "kind": "LocationSite"},
        )
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "LocationSite" in text
        assert "infrahub://schema/LocationSite" in text


async def test_make_infra_change_with_branch() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt(
            "make_infra_change",
            arguments={"description": "Remove old device", "branch": "cleanup-branch"},
        )
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "cleanup-branch" in text


async def test_make_infra_change_safety_reminders() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt("make_infra_change", arguments={"description": "Delete a rack"})
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "confirm with the user before deleting" in text
        assert "never modified directly" in text


# --- explore_schema ---


async def test_explore_schema_catalog() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt("explore_schema", arguments={})
        assert len(result.messages) == 1
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "infrahub://schema" in text
        assert "catalog" in text


async def test_explore_schema_specific_kind() -> None:
    async with Client(mcp) as client:
        result = await client.get_prompt("explore_schema", arguments={"kind": "InfraDevice"})
        text = result.messages[0].content.text  # type: ignore[attr-defined]
        assert "InfraDevice" in text
        assert "infrahub://schema/InfraDevice" in text
        assert "Attributes" in text
        assert "Relationships" in text
        assert "Filters" in text
        assert "TOON" in text


# --- prompt listing ---


async def test_all_prompts_listed() -> None:
    async with Client(mcp) as client:
        prompts = await client.list_prompts()
        names = {p.name for p in prompts}
        assert "answer_infra_question" in names
        assert "make_infra_change" in names
        assert "explore_schema" in names
