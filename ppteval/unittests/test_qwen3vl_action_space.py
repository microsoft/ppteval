"""Unit tests for Qwen3VLActionSpace."""

from ppteval.action_spaces.qwen3vl import Qwen3VLActionSpace
from ppteval.agents.qwen3vl_agent import Qwen3VLAgent


def test_parse_left_click_preserves_osworld_action():
    response = {
        "output": [
            {"type": "reasoning", "summary": [{"text": "Click the button"}]},
            {
                "type": "computer_call",
                "action": {"type": "left_click", "coordinate": [100, 200]},
            },
        ]
    }

    action = Qwen3VLActionSpace().parse_response(response)

    assert action.action_type == "left_click"
    assert action.params == {"coordinate": [100, 200]}
    assert action.reasoning == "Click the button"


def test_parse_scroll_preserves_pixels_for_executor():
    response = {
        "output": [
            {
                "type": "computer_call",
                "action": {"type": "scroll", "pixels": 5},
            }
        ]
    }

    action = Qwen3VLActionSpace().parse_response(response)

    assert action.action_type == "scroll"
    assert action.params == {"pixels": 5}


def test_parse_left_click_drag_preserves_coordinate():
    response = {
        "output": [
            {
                "type": "computer_call",
                "action": {"type": "left_click_drag", "coordinate": [300, 400]},
            }
        ]
    }

    action = Qwen3VLActionSpace().parse_response(response)

    assert action.action_type == "left_click_drag"
    assert action.params == {"coordinate": [300, 400]}


def test_parse_terminate_as_finish():
    response = {
        "output": [
            {
                "type": "computer_call",
                "action": {"type": "terminate", "status": "success"},
            }
        ]
    }

    action = Qwen3VLActionSpace().parse_response(response)

    assert action.action_type == "finish"
    assert action.params == {"status": "success"}


def test_parse_multiple_computer_calls_as_multi_action():
    response = {
        "output": [
            {
                "type": "computer_call",
                "action": {"type": "left_click", "coordinate": [10, 20]},
            },
            {
                "type": "computer_call",
                "action": {"type": "key", "keys": ["ctrl", "C"]},
            },
        ]
    }

    action = Qwen3VLActionSpace().parse_response(response)

    assert action.action_type == "multi_action"
    assert [child.action_type for child in action.params["actions"]] == ["left_click", "key"]


def test_agent_parse_keeps_raw_model_coordinates_for_history():
    agent = Qwen3VLAgent({"agent_type": "qwen3vl", "coordinate_type": "relative"})
    response = """Action: Click the center of the slide.
<tool_call>
{"name": "computer_use", "arguments": {"action": "left_click", "coordinate": [500, 500]}}
</tool_call>"""

    thought, action_type, execution_args, raw_args = agent._parse_response(
        response,
        original_width=1920,
        original_height=1080,
        processed_width=1920,
        processed_height=1088,
    )

    assert thought == "Click the center of the slide."
    assert action_type == "left_click"
    assert execution_args == {"coordinate": [960, 540]}
    assert raw_args == {"coordinate": [500, 500]}


def test_agent_previous_actions_use_raw_params_outside_visual_history():
    agent = Qwen3VLAgent({"agent_type": "qwen3vl", "coordinate_type": "relative", "history_n": 2})
    agent.set_instruction("Edit the presentation.")
    agent.actions = ["left_click: First click", "type: Enter text", "left_click: Recent click"]
    agent.action_records = [
        {
            "action_type": "left_click",
            "params": {"coordinate": [960, 540]},
            "raw_params": {"coordinate": [500, 500]},
            "thought": "First click",
        },
        {
            "action_type": "type",
            "params": {"text": "hello"},
            "raw_params": {"text": "hello"},
            "thought": "Enter text",
        },
        {
            "action_type": "left_click",
            "params": {"coordinate": [384, 216]},
            "raw_params": {"coordinate": [200, 200]},
            "thought": "Recent click",
        },
    ]

    prompt = agent._build_instruction_prompt()

    assert 'Step 1: left_click params={"coordinate": [500, 500]} - First click' in prompt
    assert "[960, 540]" not in prompt
    assert "Step 2:" not in prompt
