"""Unit tests for Qwen3VLActionSpace."""

from ppteval.action_spaces.qwen3vl import Qwen3VLActionSpace


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
