"""
Gemini Computer Use action space for parsing Google Gemini model responses.

Adapts Google Gemini Computer Use API responses into ppteval Action objects.
The Computer Use API uses normalized coordinates (0-999) and function_call format.
"""

import json
import logging
from typing import Any

from ppteval.core.base import Action, GUIState
from ppteval.action_spaces.screenenv import BaseScreenEnvActionSpace


class GeminiActionSpace(BaseScreenEnvActionSpace):
    """
    Action space for Google Gemini Computer Use API responses.

    Parses Gemini Computer Use API format with normalized coordinates (0-999).
    Handles all 14 supported UI actions: open_web_browser, wait_5_seconds, go_back,
    go_forward, search, navigate, click_at, hover_at, type_text_at, key_combination,
    scroll_document, scroll_at, drag_and_drop.
    """

    def __init__(self, screen_width: int = 1440, screen_height: int = 900):
        """
        Initialize Gemini action space.

        Args:
            screen_width: Screen width for coordinate denormalization
            screen_height: Screen height for coordinate denormalization
        """
        self.logger = logging.getLogger(__name__)
        self.screen_width = screen_width
        self.screen_height = screen_height

    def denormalize_x(self, x: int) -> int:
        """Convert normalized x coordinate (0-999) to actual pixel coordinate."""
        return int(x / 1000 * self.screen_width)

    def denormalize_y(self, y: int) -> int:
        """Convert normalized y coordinate (0-999) to actual pixel coordinate."""
        return int(y / 1000 * self.screen_height)

    def parse_response(self, response: Any) -> Action:
        """
        Parse Gemini Computer Use API response into an Action.

        Gemini Computer Use API returns responses with structure:
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "reasoning text"},
                            {
                                "function_call": {
                                    "name": "click_at",
                                    "args": {"x": 500, "y": 300}
                                }
                            }
                        ]
                    }
                }
            ]
        }

        Args:
            response: Gemini API response object or dict

        Returns:
            Action object with parsed action_type and params

        Raises:
            ValueError: If response format is invalid
        """
        try:
            # Handle response object vs dict
            if hasattr(response, 'candidates'):
                # It's a response object from google.genai
                candidates = response.candidates
                if not candidates:
                    return Action(action_type="finish", params={"message": "No response"})

                candidate = candidates[0]
                content = candidate.content
                parts = content.parts
            elif isinstance(response, dict):
                # It's a dict representation
                candidates = response.get("candidates", [])
                if not candidates:
                    return Action(action_type="finish", params={"message": "No response"})

                candidate = candidates[0]
                content = candidate.get("content", {})
                parts = content.get("parts", [])
            else:
                raise ValueError(f"Unexpected response type: {type(response)}")

            # Extract reasoning and function_call
            reasoning_parts = []
            function_call = None

            for part in parts:
                # Handle Part objects vs dicts
                if hasattr(part, 'text') and part.text:
                    reasoning_parts.append(part.text)
                elif isinstance(part, dict) and part.get("text"):
                    reasoning_parts.append(part["text"])

                if hasattr(part, 'function_call') and part.function_call:
                    function_call = part.function_call
                elif isinstance(part, dict) and part.get("function_call"):
                    function_call = part["function_call"]

            reasoning = " ".join(reasoning_parts) if reasoning_parts else None

            # If no function call, it's a finish action
            if not function_call:
                message = reasoning or "Task completed"
                return Action(action_type="finish", params={"message": message}, reasoning=reasoning)

            # Extract function name and args
            if hasattr(function_call, 'name'):
                # It's a FunctionCall object
                func_name = function_call.name
                args = dict(function_call.args) if hasattr(function_call, 'args') else {}
            elif isinstance(function_call, dict):
                # It's a dict
                func_name = function_call.get("name")
                args = function_call.get("args", {})
            else:
                raise ValueError(f"Unexpected function_call type: {type(function_call)}")

            if not func_name:
                raise ValueError("function_call missing 'name' field")

            # Transform Gemini Computer Use actions to ppteval actions
            return self._transform_gemini_action(func_name, args, reasoning)

        except Exception as e:
            self.logger.error(f"Error parsing Gemini response: {e}")
            raise ValueError(f"Failed to parse Gemini response: {e}")

    def _transform_gemini_action(
        self,
        func_name: str,
        args: dict,
        reasoning: str | None
    ) -> Action:
        """
        Transform Gemini Computer Use action to ppteval action.

        Maps Gemini's 14 supported actions to ppteval action format:
        - Denormalizes coordinates from 0-999 to actual pixels
        - Renames parameters to match ppteval conventions

        Args:
            func_name: Gemini function name (e.g., "click_at", "type_text_at")
            args: Function arguments
            reasoning: Optional reasoning text

        Returns:
            Transformed Action
        """
        # Map Gemini actions to ppteval actions
        # Most map 1:1, some need parameter transformation

        if func_name == "open_web_browser":
            return Action(action_type="open_browser", params={}, reasoning=reasoning)

        elif func_name == "wait_5_seconds":
            return Action(action_type="wait", params={"duration": 5000}, reasoning=reasoning)

        elif func_name == "go_back":
            return Action(action_type="go_back", params={}, reasoning=reasoning)

        elif func_name == "go_forward":
            return Action(action_type="go_forward", params={}, reasoning=reasoning)

        elif func_name == "search":
            return Action(action_type="search", params={}, reasoning=reasoning)

        elif func_name == "navigate":
            url = args.get("url", "")
            return Action(action_type="navigate", params={"url": url}, reasoning=reasoning)

        elif func_name == "click_at":
            x = self.denormalize_x(args.get("x", 0))
            y = self.denormalize_y(args.get("y", 0))
            return Action(
                action_type="left_click",
                params={"coordinate": [x, y]},
                reasoning=reasoning
            )

        elif func_name == "hover_at":
            x = self.denormalize_x(args.get("x", 0))
            y = self.denormalize_y(args.get("y", 0))
            return Action(
                action_type="move_mouse",
                params={"coordinate": [x, y]},
                reasoning=reasoning
            )

        elif func_name == "type_text_at":
            x = self.denormalize_x(args.get("x", 0))
            y = self.denormalize_y(args.get("y", 0))
            text = args.get("text", "")
            press_enter = args.get("press_enter", True)
            clear_before = args.get("clear_before_typing", True)

            # For ppteval, we need to break this into multiple actions
            # But for now, return a single type action
            # The orchestrator can handle the click + clear + type + enter sequence
            return Action(
                action_type="type",
                params={
                    "coordinate": [x, y],
                    "text": text,
                    "press_enter": press_enter,
                    "clear_before": clear_before
                },
                reasoning=reasoning
            )

        elif func_name == "key_combination":
            keys = args.get("keys", "")
            return Action(
                action_type="keypress",
                params={"key": [keys]},  # Wrap in list for consistency
                reasoning=reasoning
            )

        elif func_name == "scroll_document":
            direction = args.get("direction", "down")
            # Map to scroll with direction
            if direction == "down":
                return Action(action_type="scroll", params={"scroll_y": 100}, reasoning=reasoning)
            elif direction == "up":
                return Action(action_type="scroll", params={"scroll_y": -100}, reasoning=reasoning)
            elif direction == "left":
                return Action(action_type="scroll", params={"scroll_x": -100}, reasoning=reasoning)
            elif direction == "right":
                return Action(action_type="scroll", params={"scroll_x": 100}, reasoning=reasoning)
            else:
                return Action(action_type="scroll", params={"scroll_y": 100}, reasoning=reasoning)

        elif func_name == "scroll_at":
            x = self.denormalize_x(args.get("x", 0))
            y = self.denormalize_y(args.get("y", 0))
            direction = args.get("direction", "down")
            magnitude = args.get("magnitude", 800)  # 0-999 scale

            # Convert magnitude to pixel scroll amount
            scroll_amount = int(magnitude / 10)  # Scale down

            if direction == "down":
                scroll_y = scroll_amount
                scroll_x = 0
            elif direction == "up":
                scroll_y = -scroll_amount
                scroll_x = 0
            elif direction == "left":
                scroll_x = -scroll_amount
                scroll_y = 0
            elif direction == "right":
                scroll_x = scroll_amount
                scroll_y = 0
            else:
                scroll_y = scroll_amount
                scroll_x = 0

            return Action(
                action_type="scroll",
                params={
                    "coordinate": [x, y],
                    "scroll_x": scroll_x,
                    "scroll_y": scroll_y
                },
                reasoning=reasoning
            )

        elif func_name == "drag_and_drop":
            from_x = self.denormalize_x(args.get("x", 0))
            from_y = self.denormalize_y(args.get("y", 0))
            to_x = self.denormalize_x(args.get("destination_x", 0))
            to_y = self.denormalize_y(args.get("destination_y", 0))

            return Action(
                action_type="drag",
                params={
                    "from": [from_x, from_y],
                    "to": [to_x, to_y]
                },
                reasoning=reasoning
            )

        else:
            # Unknown action - this should not happen with Gemini's predefined actions
            raise ValueError(
                f"Unknown Gemini action '{func_name}'. "
                f"Valid actions: open_web_browser, navigate, go_back, go_forward, "
                f"click_at, hover_at, type_text_at, key_combination, scroll_document, "
                f"scroll_at, drag_and_drop, search, wait_5_seconds, or text-only response"
            )

    def format_state(self, state: GUIState) -> Any:
        """
        Format state for Gemini agent (returns screenshot bytes).

        Gemini expects raw screenshot bytes.

        Args:
            state: Current GUIState with screenshot

        Returns:
            Screenshot bytes for Gemini agent
        """
        return state.screenshot

    def execute(self, sandbox: Any, action: Action) -> Any:
        """Execute Gemini Computer Use actions with Gemini-specific semantics."""
        self.sandbox = sandbox
        action_type = action.action_type
        args = action.params.copy()

        if action_type in {"finish", "give_up", "terminate"}:
            return None

        if action_type == "wait":
            return self.sandbox.wait(args.get("ms", args.get("duration", 5000)))

        if action_type == "left_click":
            x, y = self._coerce_coordinate(args["coordinate"])
            return self.sandbox.left_click(x=x, y=y)

        if action_type in {"move", "move_mouse"}:
            self._normalize_coordinate_args(args)
            return self._dispatch_screenenv("move_mouse", args)

        if action_type == "type":
            return self._execute_gemini_type(args)

        if action_type in {"keypress", "press"}:
            key_value = args.pop("key", args.pop("keys", None))
            if key_value is None:
                return None
            return self.sandbox.press(key=key_value, **args)

        if action_type == "scroll":
            return self._execute_gemini_scroll(args)

        if action_type == "drag":
            return self._execute_gemini_drag(args)

        return self._dispatch_screenenv(action_type, args)

    def _execute_gemini_type(self, args: dict[str, Any]) -> Any:
        coordinate = args.pop("coordinate", None)
        if coordinate:
            x, y = self._coerce_coordinate(coordinate)
            self.sandbox.left_click(x=x, y=y)

        clear_before = args.pop("clear_before", args.pop("clear_before_typing", False))
        press_enter = args.pop("press_enter", False)
        text = args.pop("text", args.pop("content", ""))

        if clear_before:
            self.sandbox.press(key=["ctrl", "a"])
        result = self.sandbox.write(text=text, **args)
        if press_enter:
            self.sandbox.press(key=["Return"])
        return result

    def _execute_gemini_scroll(self, args: dict[str, Any]) -> Any:
        coordinate = args.pop("coordinate", None)
        if coordinate:
            x, y = self._coerce_coordinate(coordinate)
            self.sandbox.execute_command(f"xdotool mousemove --sync {x} {y}")

        scroll_y = int(args.get("scroll_y", 0) or 0)
        scroll_x = int(args.get("scroll_x", 0) or 0)
        if scroll_y:
            button = 4 if scroll_y < 0 else 5
            self.sandbox.execute_command(f"xdotool click --repeat {abs(scroll_y)} {button}")
        if scroll_x:
            button = 6 if scroll_x < 0 else 7
            self.sandbox.execute_command(f"xdotool click --repeat {abs(scroll_x)} {button}")
        return None

    def _execute_gemini_drag(self, args: dict[str, Any]) -> Any:
        if "from" in args:
            args["fr"] = args.pop("from")
        if "fr" in args and "to" in args:
            return self.sandbox.drag(
                self._coerce_coordinate(args["fr"]),
                self._coerce_coordinate(args["to"]),
            )
        return self._dispatch_screenenv("drag", args)
