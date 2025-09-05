import pytest
from agents import Runner
from agents.mcp import MCPServerStdio
from deepeval import assert_test
from deepeval.dataset.golden import Golden
from deepeval.metrics.answer_relevancy.answer_relevancy import AnswerRelevancyMetric
from deepeval.test_case.llm_test_case import LLMTestCase, ToolCall

from tests.utils import agent_context, extract_tools

goldens = [
    # Golden(
    #     name="find_devices",
    #     input="What are the devices of role edge",
    #     expected_output="""
    #         The devices with the role "edge" present in InfraHub are:
    #             atl1-edge1
    #             atl1-edge2
    #             den1-edge1
    #             den1-edge2
    #             dfw1-edge1
    #             dfw1-edge2
    #             jfk1-edge1
    #             jfk1-edge2
    #             ord1-edge1
    #             ord1-edge2
    #         """,
    #     # expected_tools=[
    #     #     ToolCall(name="weather_forecast", input_parameters={"location": "Paris"})
    #     # ]
    # ),
    Golden(
        name="find_kind",
        input="what is the proper kind for a device",
        expected_output="The proper kind for a device is InfraDevice.",
        expected_tools=[ToolCall(name="get_schema_mapping", input_parameters=None)],
    ),
]


@pytest.mark.parametrize("golden", goldens)
async def test_llm_app(local_mcp_server: MCPServerStdio, main_prompt: str, golden: Golden) -> None:
    # NOTE: it should be possible to mode agent_context to a fixture, need to investigate
    async with agent_context(
        name="Assistant",
        instructions=main_prompt,
        mcp_servers=[local_mcp_server],
    ) as agent:
        result = await Runner.run(agent, input=golden.input)

        # Extract the `tools` called during the run
        # This is useful to check if the agent called the expected tools
        # and to compare the input parameters of the tools with the expected ones
        # Currently, the method doesn't return the output of the tools, need to investigate if it's possible
        tools_called = extract_tools(result)

        test_case = LLMTestCase(
            name=golden.name,
            input=golden.input,
            actual_output=result.final_output,
            tools_called=tools_called,
            expected_tools=golden.expected_tools,
        )

        assert_test(
            test_case=test_case,
            metrics=[
                AnswerRelevancyMetric(),
                # ToolCorrectnessMetric(evaluation_params=[ToolCallParams.INPUT_PARAMETERS], strict_mode=True, should_exact_match=True)
            ],
        )
