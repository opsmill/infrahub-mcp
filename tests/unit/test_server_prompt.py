from infrahub_mcp.instructions import build_instructions
from infrahub_mcp.server import _config, infrahub_agent


def test_infrahub_agent_prompt_returns_content() -> None:
    result = infrahub_agent()
    assert isinstance(result, str)
    assert len(result) > 100
    assert "infrahub://schema" in result
    assert "get_nodes" in result
    assert "node_upsert" in result
    assert "session branch" in result


def test_infrahub_agent_prompt_includes_the_server_instructions() -> None:
    """FR-009: the prompt and the server instructions come from one source."""
    result = infrahub_agent()
    assert build_instructions(read_only=_config.read_only, resources_as_tools=_config.resources_as_tools) in result
    assert "## Data formats" not in result
    assert "## Schema discovery" not in result
