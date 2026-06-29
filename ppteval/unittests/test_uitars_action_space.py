"""
Unit tests for UITARSActionSpace.

Tests UI-TARS response parsing and action transformations.
"""

import json
import pytest
from unittest.mock import Mock, patch

from ppteval.action_spaces.uitars import UITARSActionSpace
from ppteval.core.base import Action, GUIState


class TestUITARSActionSpaceInit:
    """Tests for UITARSActionSpace initialization."""

    def test_init_creates_action_space(self):
        """Test that UITARSActionSpace initializes successfully."""
        action_space = UITARSActionSpace()
        assert action_space is not None
        assert action_space.logger is not None


class TestUITARSActionSpaceParseResponse:
    """Tests for UITARSActionSpace.parse_response()."""

    def test_parse_valid_click_action(self):
        """Test parsing a valid click action."""
        response = {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"text": "I will click the button"}]
                },
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",
                        "x": 100,
                        "y": 200
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "click"
        assert action.params == {"x": 100, "y": 200}
        assert action.reasoning == "I will click the button"

    def test_parse_double_click_action(self):
        """Test parsing double_click action (converted by UITARS agent from left_double)."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "double_click",
                        "x": 300,
                        "y": 400
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "double_click"
        assert action.params == {"x": 300, "y": 400}

    def test_parse_right_click_action(self):
        """Test parsing right_click action (converted by UITARS agent from right_single)."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "right_click",
                        "x": 500,
                        "y": 600
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "right_click"
        assert action.params == {"x": 500, "y": 600}

    def test_parse_type_action_with_content(self):
        """Test parsing type action with content param transforms to text."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "type",
                        "content": "Hello World"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "type"
        assert action.params == {"text": "Hello World"}

    def test_parse_keypress_action(self):
        """Test parsing keypress action (converted by UITARS agent from hotkey)."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "keypress",
                        "key": "ctrl c"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "keypress"
        assert action.params == {"keys": ["ctrl", "c"]}

    def test_parse_keypress_with_multiple_keys(self):
        """Test parsing keypress with multiple keys."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "keypress",
                        "key": "ctrl shift s"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "keypress"
        assert action.params == {"keys": ["ctrl", "shift", "s"]}

    def test_parse_scroll_down(self):
        """Test parsing scroll down action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "scroll",
                        "direction": "down"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "scroll"
        assert action.params["scroll_y"] == 10
        assert action.params["scroll_x"] == 0

    def test_parse_scroll_up(self):
        """Test parsing scroll up action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "scroll",
                        "direction": "up"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "scroll"
        assert action.params["scroll_y"] == -10
        assert action.params["scroll_x"] == 0

    def test_parse_scroll_right(self):
        """Test parsing scroll right action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "scroll",
                        "direction": "right"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "scroll"
        assert action.params["scroll_x"] == 10
        assert action.params["scroll_y"] == 0

    def test_parse_scroll_left(self):
        """Test parsing scroll left action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "scroll",
                        "direction": "left"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "scroll"
        assert action.params["scroll_x"] == -10
        assert action.params["scroll_y"] == 0

    def test_parse_drag_action_with_path(self):
        """Test parsing drag action with path converts to fr/to."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "drag",
                        "path": [
                            {"x": 100, "y": 200},
                            {"x": 300, "y": 400}
                        ]
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "drag"
        assert action.params["fr"] == (100, 200)
        assert action.params["to"] == (300, 400)

    def test_parse_wait_action(self):
        """Test parsing wait action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "wait"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "wait"
        assert action.params == {}

    def test_parse_finished_action_with_content(self):
        """Test parsing finished() action with content."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "finished",
                        "content": "Task completed successfully"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "finish"
        assert action.params == {}
        assert action.reasoning == "Task completed successfully"

    def test_parse_finish_action(self):
        """Test parsing finish action (alternative name)."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "finish",
                        "message": "All done"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "finish"
        assert action.params == {}
        assert action.reasoning == "All done"

    def test_parse_finish_message_done(self):
        """Test parsing finish via DONE in message content."""
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "DONE. Task completed."}]
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "finish"
        assert action.params == {}
        assert "DONE" in action.reasoning

    def test_parse_with_reasoning(self):
        """Test parsing action extracts reasoning from summary."""
        response = {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"text": "Thought: I need to click the submit button"}]
                },
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",
                        "x": 100,
                        "y": 200
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "click"
        assert "submit button" in action.reasoning

    def test_parse_json_string_input(self):
        """Test parsing accepts JSON string input."""
        response_str = json.dumps({
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",
                        "x": 10,
                        "y": 20
                    }
                }
            ]
        })

        action_space = UITARSActionSpace()
        action = action_space.parse_response(response_str)

        assert action.action_type == "click"
        assert action.params == {"x": 10, "y": 20}

    def test_parse_invalid_json_raises_error(self):
        """Test parsing invalid JSON raises ValueError."""
        action_space = UITARSActionSpace()

        with pytest.raises(ValueError, match="Invalid JSON"):
            action_space.parse_response("not valid json {")

    def test_parse_missing_computer_call_raises_error(self):
        """Test parsing response without computer_call raises ValueError."""
        response = {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"text": "Just thinking"}]
                }
            ]
        }

        action_space = UITARSActionSpace()

        with pytest.raises(ValueError, match="No 'computer_call'"):
            action_space.parse_response(response)

    def test_parse_missing_action_raises_error(self):
        """Test parsing computer_call without action raises ValueError."""
        response = {
            "output": [
                {
                    "type": "computer_call"
                }
            ]
        }

        action_space = UITARSActionSpace()

        with pytest.raises(ValueError, match="missing 'action'"):
            action_space.parse_response(response)

    def test_parse_missing_action_type_raises_error(self):
        """Test parsing action without type raises ValueError."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "x": 100,
                        "y": 200
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()

        with pytest.raises(ValueError, match="missing 'type'"):
            action_space.parse_response(response)


class TestUITARSActionSpaceFormatState:
    """Tests for UITARSActionSpace.format_state()."""

    def test_format_state_returns_screenshot_bytes(self):
        """Test that format_state returns screenshot bytes."""
        screenshot = b"fake_screenshot_data"
        state = GUIState(screenshot=screenshot, done=False)

        action_space = UITARSActionSpace()
        result = action_space.format_state(state)

        assert result == screenshot

    def test_format_state_with_done_state(self):
        """Test that format_state works with done=True state."""
        screenshot = b"final_screenshot"
        state = GUIState(screenshot=screenshot, done=True)

        action_space = UITARSActionSpace()
        result = action_space.format_state(state)

        assert result == screenshot


class TestUITARSActionSpaceIntegration:
    """Integration tests for UITARSActionSpace."""

    def test_full_workflow_with_finished(self):
        """Test full workflow: parse multiple actions ending with finished."""
        # Parse a regular action
        response1 = {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"text": "Thought: I will type the text"}]
                },
                {
                    "type": "computer_call",
                    "action": {
                        "type": "type",
                        "content": "Test input"
                    }
                }
            ]
        }

        action_space = UITARSActionSpace()
        action1 = action_space.parse_response(response1)

        assert action1.action_type == "type"
        assert action1.params["text"] == "Test input"

        # Parse a finished action
        response2 = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "finished",
                        "content": "Input submitted successfully"
                    }
                }
            ]
        }

        action2 = action_space.parse_response(response2)

        assert action2.action_type == "finish"
        assert "submitted" in action2.reasoning
