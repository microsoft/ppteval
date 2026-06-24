"""
Unit tests for ClaudeActionSpace.

Tests Claude Computer Use API response parsing and action transformations.
"""

import json
from io import BytesIO
from unittest.mock import Mock

import pytest
from PIL import Image

from ppteval.action_spaces.claude import ClaudeActionSpace
from ppteval.core.base import Action, GUIState


class TestClaudeActionSpaceInit:
    """Tests for ClaudeActionSpace initialization."""

    def test_init_creates_action_space(self):
        """Test that ClaudeActionSpace initializes successfully."""
        action_space = ClaudeActionSpace()
        assert action_space is not None
        assert action_space.logger is not None


class TestClaudeActionSpaceParseResponse:
    """Tests for ClaudeActionSpace.parse_response()."""

    def test_parse_left_click(self):
        """Test parsing left_click action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "left_click",
                        "coordinate": [100, 200]
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "left_click"
        assert action.params == {"coordinate": [100, 200]}

    def test_parse_right_click(self):
        """Test parsing right_click action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "right_click",
                        "coordinate": [300, 400]
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "right_click"
        assert action.params == {"coordinate": [300, 400]}

    def test_parse_middle_click(self):
        """Test parsing middle_click action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "middle_click",
                        "coordinate": [500, 600]
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "middle_click"
        assert action.params == {"coordinate": [500, 600]}

    def test_parse_double_click(self):
        """Test parsing double_click action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "double_click",
                        "coordinate": [150, 250]
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "double_click"
        assert action.params == {"coordinate": [150, 250]}

    def test_parse_triple_click(self):
        """Test parsing triple_click action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "triple_click",
                        "coordinate": [700, 800]
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "triple_click"
        assert action.params == {"coordinate": [700, 800]}

    def test_parse_mouse_move(self):
        """Test parsing mouse_move action converts to move."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "mouse_move",
                        "coordinate": [400, 500]
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "mouse_move"
        assert action.params == {"coordinate": [400, 500]}

    def test_parse_key_action(self):
        """Test parsing key action converts to keypress."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "key",
                        "text": "ctrl+c"
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "key"
        assert action.params == {"text": "ctrl+c"}

    def test_parse_type_action(self):
        """Test parsing type action."""
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

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "type"
        assert action.params == {"text": "Hello World"}

    def test_parse_left_click_drag(self):
        """Test parsing left_click_drag action converts to drag."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "left_click_drag",
                        "coordinate": [100, 200],
                        "end_coordinate": [300, 400]
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "left_click_drag"
        assert action.params == {
            "coordinate": [100, 200],
            "end_coordinate": [300, 400],
        }

    def test_parse_screenshot_action(self):
        """Test parsing screenshot action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "screenshot"
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "screenshot"
        assert action.params == {}

    def test_parse_cursor_position_action(self):
        """Test parsing cursor_position action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "cursor_position"
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "cursor_position"
        assert action.params == {}

    def test_parse_zoom_action(self):
        """Test parsing 2025-11-24 zoom action."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "zoom",
                        "region": [10, 20, 110, 120]
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "zoom"
        assert action.params == {"region": [10, 20, 110, 120]}

    def test_parse_with_reasoning(self):
        """Test parsing action extracts reasoning from output."""
        response = {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"text": "I will click the button"}]
                },
                {
                    "type": "computer_call",
                    "action": {
                        "type": "left_click",
                        "coordinate": [100, 200]
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "left_click"
        assert action.reasoning == "I will click the button"

    def test_parse_finish_message(self):
        """Test parsing finish via DONE in message."""
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [{"text": "DONE. Task completed."}]
                }
            ]
        }

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response)

        assert action.action_type == "finish"
        assert action.params == {}
        assert "DONE" in action.reasoning

    def test_parse_json_string_input(self):
        """Test parsing accepts JSON string input."""
        response_str = json.dumps({
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "left_click",
                        "coordinate": [10, 20]
                    }
                }
            ]
        })

        action_space = ClaudeActionSpace()
        action = action_space.parse_response(response_str)

        assert action.action_type == "left_click"
        assert action.params["coordinate"] == [10, 20]

    def test_parse_invalid_json_raises_error(self):
        """Test parsing invalid JSON raises ValueError."""
        action_space = ClaudeActionSpace()

        with pytest.raises(ValueError, match="Invalid JSON"):
            action_space.parse_response("not valid json {")

    def test_parse_missing_output_raises_error(self):
        """Test parsing response without output raises ValueError."""
        response = {"status": "ok"}

        action_space = ClaudeActionSpace()

        with pytest.raises(ValueError, match="No.*found"):
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

        action_space = ClaudeActionSpace()

        with pytest.raises(ValueError, match="missing 'action'"):
            action_space.parse_response(response)

    def test_parse_missing_action_type_raises_error(self):
        """Test parsing action without type raises ValueError."""
        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "coordinate": [100, 200]
                    }
                }
            ]
        }

        action_space = ClaudeActionSpace()

        with pytest.raises(ValueError, match="missing 'type'"):
            action_space.parse_response(response)


class TestClaudeActionSpaceFormatState:
    """Tests for ClaudeActionSpace.format_state()."""

    def test_format_state_returns_screenshot_bytes(self):
        """Test that format_state returns screenshot bytes."""
        screenshot = b"fake_screenshot_data"
        state = GUIState(screenshot=screenshot, done=False)

        action_space = ClaudeActionSpace()
        result = action_space.format_state(state)

        assert result == screenshot

    def test_format_state_with_done_state(self):
        """Test that format_state works with done=True state."""
        screenshot = b"final_screenshot"
        state = GUIState(screenshot=screenshot, done=True)

        action_space = ClaudeActionSpace()
        result = action_space.format_state(state)

        assert result == screenshot


class TestClaudeActionSpaceExecute:
    """Tests for ClaudeActionSpace.execute()."""

    def test_execute_zoom_returns_cropped_png_bytes(self):
        """Test that zoom crops the requested screenshot region."""
        image = Image.new("RGB", (200, 150), color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")

        sandbox = Mock()
        sandbox.desktop_screenshot.return_value = buffer.getvalue()

        result = ClaudeActionSpace().execute(
            sandbox,
            Action("zoom", {"region": [10, 20, 110, 120]}),
        )

        cropped = Image.open(BytesIO(result))
        assert cropped.size == (100, 100)
        sandbox.desktop_screenshot.assert_called_once_with()


class TestClaudeActionSpaceIntegration:
    """Integration tests for ClaudeActionSpace."""

    def test_full_workflow_multiple_actions(self):
        """Test full workflow with multiple action types."""
        action_space = ClaudeActionSpace()

        # Parse a mouse move
        response1 = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "mouse_move",
                        "coordinate": [100, 200]
                    }
                }
            ]
        }
        action1 = action_space.parse_response(response1)
        assert action1.action_type == "mouse_move"

        # Parse a click
        response2 = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "left_click",
                        "coordinate": [100, 200]
                    }
                }
            ]
        }
        action2 = action_space.parse_response(response2)
        assert action2.action_type == "left_click"

        # Parse a type
        response3 = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "type",
                        "text": "Test"
                    }
                }
            ]
        }
        action3 = action_space.parse_response(response3)
        assert action3.action_type == "type"

    def test_unknown_action_raises_error(self):
        """Test that unknown actions raise ValueError."""
        action_space = ClaudeActionSpace()

        response = {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "unknown_action_type",
                        "param1": "value1"
                    }
                }
            ]
        }

        with pytest.raises(ValueError, match="Unknown Claude Computer Use action 'unknown_action_type'"):
            action_space.parse_response(response)
