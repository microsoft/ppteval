"""
Unit tests for CUAActionSpace.

Tests CUA (Computer Use Agent) response parsing and action transformations.
"""

import json
import pytest
from unittest.mock import Mock, patch

from ppteval.action_spaces.cua import CUAActionSpace
from ppteval.core.base import Action, GUIState


class TestCUAActionSpaceInit:
    """Tests for CUAActionSpace initialization."""

    def test_init_creates_action_space(self):
        """Test that CUAActionSpace initializes successfully."""
        action_space = CUAActionSpace()
        assert action_space is not None
        assert action_space.logger is not None


class TestCUAActionSpaceParseResponse:
    """Tests for CUAActionSpace.parse_response()."""

    def test_parse_valid_click_action(self):
        """Test parsing a valid click action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",
                        "x": 100,
                        "y": 200,
                        "button": "left"
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "click"
        assert action.params == {"x": 100, "y": 200, "button": "left"}

    def test_parse_click_default_button(self):
        """Test click action defaults to left button."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",
                        "x": 50,
                        "y": 75
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "click"
        assert action.params == {"x": 50, "y": 75}

    def test_parse_right_click(self):
        """Test parsing right click action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",
                        "x": 300,
                        "y": 400,
                        "button": "right"
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "click"
        assert action.params == {"x": 300, "y": 400, "button": "right"}

    def test_parse_type_action(self):
        """Test parsing type action transforms to write."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "type",
                        "text": "Hello World"
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "type"
        assert action.params == {"text": "Hello World"}

    def test_parse_keypress_action(self):
        """Test parsing keypress action transforms to press with key param."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "keypress",
                        "keys": "ctrl+c"
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "keypress"
        assert action.params == {"keys": "ctrl+c"}

    def test_parse_move_action(self):
        """Test parsing move action transforms to move_mouse."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "move",
                        "x": 500,
                        "y": 600
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "move"
        assert action.params == {"x": 500, "y": 600}

    def test_parse_scroll_with_direction(self):
        """Test parsing scroll action with direction."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "scroll",
                        "direction": "down",
                        "amount": 5
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "scroll"
        assert action.params == {"direction": "down", "amount": 5}

    def test_parse_scroll_with_coordinates(self):
        """Test parsing scroll action with scroll_x and scroll_y."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "scroll",
                        "x": 100,
                        "y": 200,
                        "scroll_x": 0,
                        "scroll_y": 10
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "scroll"
        assert action.params["scroll_x"] == 0
        assert action.params["scroll_y"] == 10

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
                            {"x": 150, "y": 250},
                            {"x": 300, "y": 400}
                        ]
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "drag"
        assert action.params["path"] == [
            {"x": 100, "y": 200},
            {"x": 150, "y": 250},
            {"x": 300, "y": 400},
        ]

    def test_parse_wait_action_with_duration(self):
        """Test parsing wait action converts duration to milliseconds."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "wait",
                        "duration": 3.5
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "wait"
        assert action.params["duration"] == 3.5

    def test_parse_wait_action_default_duration(self):
        """Test parsing wait action without duration defaults to 5000ms."""
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

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "wait"
        assert action.params == {}

    def test_parse_finish_action_explicit(self):
        """Test parsing explicit finish action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "finish",
                        "message": "Task completed successfully"
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "finish"
        assert action.params == {}
        assert action.reasoning == "Task completed successfully"

    def test_parse_finish_message_done(self):
        """Test parsing finish via DONE in message content."""
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [{"text": "DONE. Task completed."}]
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "finish"
        assert action.params == {}
        assert "DONE" in action.reasoning

    def test_parse_finish_call_alternative_format(self):
        """Test parsing finish via call type alternative format."""
        response = {
            "output": [
                {
                    "type": "call",
                    "action": {
                        "type": "finish",
                        "message": "All done"
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "finish"
        assert action.params == {}
        assert action.reasoning == "All done"

    def test_parse_user_interaction(self):
        """Test parsing user_interaction returns give_up."""
        response = {
            "output": [
                {
                    "type": "user_interaction"
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "give_up"
        assert action.params == {}
        assert "user input" in action.reasoning.lower()

    def test_parse_with_reasoning(self):
        """Test parsing action extracts reasoning from message."""
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [{"text": "I will click the button"}]
                },
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",
                        "x": 100,
                        "y": 200,
                        "button": "left"
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "click"
        assert action.reasoning == "I will click the button"

    def test_parse_json_string_input(self):
        """Test parsing accepts JSON string input."""
        response_str = json.dumps({
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",
                        "x": 10,
                        "y": 20,
                        "button": "left"
                    }
                }
            ]
        })

        action_space = CUAActionSpace()
        action = action_space.parse_response(response_str)

        assert action.action_type == "click"
        assert action.params == {"x": 10, "y": 20, "button": "left"}

    def test_parse_invalid_json_raises_error(self):
        """Test parsing invalid JSON raises ValueError."""
        action_space = CUAActionSpace()

        with pytest.raises(ValueError, match="Invalid JSON"):
            action_space.parse_response("not valid json {")

    def test_parse_missing_output_raises_error(self):
        """Test parsing response without output raises ValueError."""
        response = {"status": "ok"}

        action_space = CUAActionSpace()

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

        action_space = CUAActionSpace()

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

        action_space = CUAActionSpace()

        with pytest.raises(ValueError, match="missing 'type'"):
            action_space.parse_response(response)


class TestCUAActionSpaceFormatState:
    """Tests for CUAActionSpace.format_state()."""

    def test_format_state_returns_screenshot_bytes(self):
        """Test that format_state returns screenshot bytes."""
        screenshot = b"fake_screenshot_data"
        state = GUIState(screenshot=screenshot, done=False)

        action_space = CUAActionSpace()
        result = action_space.format_state(state)

        assert result == screenshot

    def test_format_state_with_done_state(self):
        """Test that format_state works with done=True state."""
        screenshot = b"final_screenshot"
        state = GUIState(screenshot=screenshot, done=True)

        action_space = CUAActionSpace()
        result = action_space.format_state(state)

        assert result == screenshot


class TestCUAActionSpaceIntegration:
    """Integration tests for CUAActionSpace."""

    def test_full_workflow_click_action(self):
        """Test full workflow: parse response, format state."""
        # Parse a click action
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",
                        "x": 150,
                        "y": 250,
                        "button": "left"
                    }
                }
            ]
        }

        action_space = CUAActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "click"
        assert action.params["x"] == 150
        assert action.params["y"] == 250

        # Format state for next iteration
        screenshot = b"next_screenshot"
        state = GUIState(screenshot=screenshot, done=False)
        formatted = action_space.format_state(state)

        assert formatted == screenshot
