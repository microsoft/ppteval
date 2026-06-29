"""
Unit tests for GeminiActionSpace.

Tests parsing of Gemini Computer Use API responses with all 14 supported actions,
coordinate denormalization, and function_call/function_response patterns.
"""

import pytest

from ppteval.action_spaces.gemini import GeminiActionSpace
from ppteval.core.base import Action


@pytest.fixture
def action_space():
    """Create GeminiActionSpace with standard screen size."""
    return GeminiActionSpace(screen_width=1440, screen_height=900)


@pytest.fixture
def small_action_space():
    """Create GeminiActionSpace with small screen size for coordinate testing."""
    return GeminiActionSpace(screen_width=100, screen_height=100)


class TestCoordinateDenormalization:
    """Test coordinate conversion from normalized (0-999) to pixels."""

    def test_denormalize_x_middle(self, action_space):
        """Test denormalizing x coordinate at middle of screen."""
        # 500/1000 * 1440 = 720
        assert action_space.denormalize_x(500) == 720

    def test_denormalize_y_middle(self, action_space):
        """Test denormalizing y coordinate at middle of screen."""
        # 500/1000 * 900 = 450
        assert action_space.denormalize_y(500) == 450

    def test_denormalize_x_edges(self, action_space):
        """Test denormalizing x coordinate at edges."""
        assert action_space.denormalize_x(0) == 0
        assert action_space.denormalize_x(999) == 1438  # 999/1000 * 1440 = 1438.56

    def test_denormalize_y_edges(self, action_space):
        """Test denormalizing y coordinate at edges."""
        assert action_space.denormalize_y(0) == 0
        assert action_space.denormalize_y(999) == 899  # 999/1000 * 900 = 899.1

    def test_denormalize_small_screen(self, small_action_space):
        """Test denormalization on small screen."""
        assert small_action_space.denormalize_x(500) == 50
        assert small_action_space.denormalize_y(500) == 50


class TestOpenWebBrowser:
    """Test parsing open_web_browser action."""

    def test_open_web_browser(self, action_space):
        """Test parsing open_web_browser function call."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": "Opening browser"
                    }, {
                        "function_call": {
                            "name": "open_web_browser",
                            "args": {}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "open_browser"
        assert action.params == {}
        assert action.reasoning == "Opening browser"


class TestWaitAction:
    """Test parsing wait_5_seconds action."""

    def test_wait_5_seconds(self, action_space):
        """Test parsing wait_5_seconds function call."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "wait_5_seconds",
                            "args": {}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "wait"
        assert action.params == {"duration": 5000}


class TestNavigationActions:
    """Test parsing navigation actions (go_back, go_forward, search, navigate)."""

    def test_go_back(self, action_space):
        """Test parsing go_back function call."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "go_back",
                            "args": {}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "go_back"
        assert action.params == {}

    def test_go_forward(self, action_space):
        """Test parsing go_forward function call."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "go_forward",
                            "args": {}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "go_forward"
        assert action.params == {}

    def test_search(self, action_space):
        """Test parsing search function call."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "search",
                            "args": {}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "search"
        assert action.params == {}

    def test_navigate(self, action_space):
        """Test parsing navigate function call with URL."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "navigate",
                            "args": {"url": "https://example.com"}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "navigate"
        assert action.params == {"url": "https://example.com"}


class TestClickActions:
    """Test parsing click_at action with coordinate denormalization."""

    def test_click_at_center(self, action_space):
        """Test parsing click_at at center of screen."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": "Clicking center"
                    }, {
                        "function_call": {
                            "name": "click_at",
                            "args": {"x": 500, "y": 500}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "left_click"
        assert action.params == {"coordinate": [720, 450]}  # 500/1000 * 1440, 500/1000 * 900
        assert action.reasoning == "Clicking center"

    def test_click_at_top_left(self, action_space):
        """Test parsing click_at at top-left corner."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "click_at",
                            "args": {"x": 0, "y": 0}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "left_click"
        assert action.params == {"coordinate": [0, 0]}

    def test_click_at_bottom_right(self, action_space):
        """Test parsing click_at at bottom-right corner."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "click_at",
                            "args": {"x": 999, "y": 999}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "left_click"
        assert action.params == {"coordinate": [1438, 899]}


class TestHoverAction:
    """Test parsing hover_at action."""

    def test_hover_at(self, action_space):
        """Test parsing hover_at function call."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "hover_at",
                            "args": {"x": 300, "y": 200}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "move_mouse"
        # 300/1000 * 1440 = 432, 200/1000 * 900 = 180
        assert action.params == {"coordinate": [432, 180]}


class TestTypeTextAction:
    """Test parsing type_text_at action."""

    def test_type_text_at_full(self, action_space):
        """Test parsing type_text_at with all parameters."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "type_text_at",
                            "args": {
                                "x": 400,
                                "y": 300,
                                "text": "Hello World",
                                "press_enter": True,
                                "clear_before_typing": True
                            }
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "type"
        # 400/1000 * 1440 = 576, 300/1000 * 900 = 270
        assert action.params == {
            "coordinate": [576, 270],
            "text": "Hello World",
            "press_enter": True,
            "clear_before": True
        }

    def test_type_text_at_no_enter(self, action_space):
        """Test parsing type_text_at without pressing enter."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "type_text_at",
                            "args": {
                                "x": 500,
                                "y": 500,
                                "text": "Test",
                                "press_enter": False,
                                "clear_before_typing": False
                            }
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "type"
        assert action.params["press_enter"] is False
        assert action.params["clear_before"] is False


class TestKeyCombination:
    """Test parsing key_combination action."""

    def test_key_combination_single(self, action_space):
        """Test parsing key_combination with single key."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "key_combination",
                            "args": {"keys": "Enter"}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "keypress"
        assert action.params == {"key": ["Enter"]}

    def test_key_combination_combo(self, action_space):
        """Test parsing key_combination with key combo."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "key_combination",
                            "args": {"keys": "Control+C"}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "keypress"
        assert action.params == {"key": ["Control+C"]}


class TestScrollActions:
    """Test parsing scroll_document and scroll_at actions."""

    def test_scroll_document_down(self, action_space):
        """Test parsing scroll_document down."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "scroll_document",
                            "args": {"direction": "down"}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "scroll"
        assert action.params == {"scroll_y": 100}

    def test_scroll_document_up(self, action_space):
        """Test parsing scroll_document up."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "scroll_document",
                            "args": {"direction": "up"}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "scroll"
        assert action.params == {"scroll_y": -100}

    def test_scroll_document_left(self, action_space):
        """Test parsing scroll_document left."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "scroll_document",
                            "args": {"direction": "left"}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "scroll"
        assert action.params == {"scroll_x": -100}

    def test_scroll_document_right(self, action_space):
        """Test parsing scroll_document right."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "scroll_document",
                            "args": {"direction": "right"}
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "scroll"
        assert action.params == {"scroll_x": 100}

    def test_scroll_at_down(self, action_space):
        """Test parsing scroll_at with coordinates and direction."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "scroll_at",
                            "args": {
                                "x": 500,
                                "y": 500,
                                "direction": "down",
                                "magnitude": 800
                            }
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "scroll"
        assert action.params == {
            "coordinate": [720, 450],
            "scroll_x": 0,
            "scroll_y": 80  # 800/10
        }

    def test_scroll_at_up(self, action_space):
        """Test parsing scroll_at up."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "scroll_at",
                            "args": {
                                "x": 500,
                                "y": 500,
                                "direction": "up",
                                "magnitude": 400
                            }
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.params["scroll_y"] == -40  # 400/10, negative for up


class TestDragAndDrop:
    """Test parsing drag_and_drop action."""

    def test_drag_and_drop(self, action_space):
        """Test parsing drag_and_drop function call."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": "Dragging element"
                    }, {
                        "function_call": {
                            "name": "drag_and_drop",
                            "args": {
                                "x": 100,
                                "y": 200,
                                "destination_x": 300,
                                "destination_y": 400
                            }
                        }
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "drag"
        # 100/1000 * 1440 = 144, 200/1000 * 900 = 180
        # 300/1000 * 1440 = 432, 400/1000 * 900 = 360
        assert action.params == {
            "from": [144, 180],
            "to": [432, 360]
        }
        assert action.reasoning == "Dragging element"


class TestFinishAction:
    """Test parsing finish action (no function_call)."""

    def test_finish_with_text(self, action_space):
        """Test parsing response with text only (no function call)."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": "Task completed successfully"
                    }]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.action_type == "finish"
        assert action.params == {"message": "Task completed successfully"}
        assert action.reasoning == "Task completed successfully"

    def test_finish_no_candidates(self, action_space):
        """Test parsing response with no candidates."""
        response = {"candidates": []}

        action = action_space.parse_response(response)
        assert action.action_type == "finish"
        assert action.params == {"message": "No response"}


class TestMultipleReasoningParts:
    """Test parsing responses with multiple text parts."""

    def test_multiple_reasoning_parts(self, action_space):
        """Test combining multiple text parts into reasoning."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [
                        {"text": "First thought."},
                        {"text": "Second thought."},
                        {
                            "function_call": {
                                "name": "click_at",
                                "args": {"x": 500, "y": 500}
                            }
                        }
                    ]
                }
            }]
        }

        action = action_space.parse_response(response)
        assert action.reasoning == "First thought. Second thought."


class TestUnknownAction:
    """Test parsing unknown action types."""

    def test_unknown_action(self, action_space):
        """Test parsing unknown action raises ValueError."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "unknown_action",
                            "args": {"param1": "value1"}
                        }
                    }]
                }
            }]
        }

        with pytest.raises(ValueError, match="Unknown Gemini action 'unknown_action'"):
            action_space.parse_response(response)


class TestErrorHandling:
    """Test error handling for invalid responses."""

    def test_invalid_response_type(self, action_space):
        """Test parsing invalid response type raises ValueError."""
        with pytest.raises(ValueError, match="Unexpected response type"):
            action_space.parse_response("invalid string response")

    def test_missing_function_name(self, action_space):
        """Test parsing function_call without name raises ValueError."""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "args": {"x": 100}
                        }
                    }]
                }
            }]
        }

        with pytest.raises(ValueError, match="missing 'name' field"):
            action_space.parse_response(response)
