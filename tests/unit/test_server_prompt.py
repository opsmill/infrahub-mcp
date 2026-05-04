from infrahub_mcp.server import infrahub_agent


def test_infrahub_agent_prompt_returns_content() -> None:
    result = infrahub_agent()
    assert isinstance(result, str)
    assert len(result) > 100
    assert "infrahub://schema" in result
    assert "get_nodes" in result
    assert "node_upsert" in result
    assert "session branch" in result
