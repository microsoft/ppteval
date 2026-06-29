"""
Claude action space for parsing Anthropic Claude responses.

Adapts Claude Computer Use API responses into ppteval Action objects.
"""

import json
import logging
import shlex
import time
from io import BytesIO
from typing import Any

from PIL import Image  # pyright: ignore[reportMissingModuleSource]

from ppteval.core.base import Action, GUIState
from ppteval.action_spaces.screenenv import BaseScreenEnvActionSpace


class ClaudeActionSpace(BaseScreenEnvActionSpace):
    """
    Action space for Anthropic Claude Computer Use API responses.

    Parses Claude's tool call responses with computer actions
    and translates them into ppteval Action objects.
    """

    def __init__(self):
        """Initialize Claude action space."""
        self.logger = logging.getLogger(__name__)

    def parse_response(self, response: str | dict) -> Action:
        """
        Parse Claude response into an Action.

        Claude returns JSON with structure:
        {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "left_click",  # or other action types
                        "coordinate": [100, 200],
                        ...other params...
                    }
                }
            ]
        }

        Args:
            response: Claude response (JSON string or dict)

        Returns:
            Action object with parsed action_type and params

        Raises:
            ValueError: If response format is invalid
        """
        try:
            # Parse JSON if string
            if isinstance(response, str):
                response_data = json.loads(response)
            else:
                response_data = response

            output = response_data.get("output", [])

            # Check for finish message (DONE in message content)
            for item in output:
                if item.get("type") == "message":
                    content = item.get("content", [])
                    if content and isinstance(content, list):
                        text = content[0].get("text", "") if content else ""
                        if "DONE" in text:
                            return Action(
                                action_type="finish",
                                params={},
                                reasoning=text
                            )

            # Find action (computer_call or call)
            action_item = None
            for item in output:
                if item.get("type") in ["computer_call", "call"]:
                    action_item = item
                    break

            if not action_item:
                raise ValueError("No 'computer_call' or 'call' found in Claude response")

            # Extract action
            action_data = action_item.get("action", {})
            if not action_data:
                raise ValueError("Action item missing 'action' field")

            action_type = action_data.get("type")
            if not action_type:
                raise ValueError("Action missing 'type' field")

            # Handle "computer" wrapper - Claude API returns tool_use with type "computer"
            # that contains the actual action nested inside
            if action_type == "computer":
                # Extract the nested action
                action_type = action_data.get("action")
                if not action_type:
                    raise ValueError("Computer action missing nested 'action' field")
                # The other parameters are at the same level in action_data

            # Handle finish action
            if action_type == "finish":
                return Action(
                    action_type="finish",
                    params={},
                    reasoning=action_data.get("message", "Task completed")
                )

            valid_action_types = {
                "screenshot",
                "wait",
                "mouse_move",
                "left_click",
                "right_click",
                "double_click",
                "key",
                "type",
                "left_click_drag",
                "middle_click",
                "triple_click",
                "left_mouse_down",
                "left_mouse_up",
                "scroll",
                "hold_key",
                "cursor_position",
                "zoom",
                "finish",
            }
            if action_type not in valid_action_types:
                raise ValueError(
                    f"Unknown Claude Computer Use action '{action_type}'. "
                    f"Valid actions: left_click, right_click, middle_click, double_click, "
                    f"triple_click, mouse_move, key, type, scroll, wait, left_click_drag, finish, "
                    f"screenshot, cursor_position, hold_key, left_mouse_down, left_mouse_up, zoom"
                )

            # Preserve Claude's native action shape. Execution semantics differ
            # from CUA for shared names such as click, key, wait, and drag.
            params = {key: value for key, value in action_data.items() if key not in {"type", "action"}}

            # Extract reasoning if present
            reasoning = None
            for item in output:
                if item.get("type") == "reasoning":
                    summary = item.get("summary", [])
                    if summary and isinstance(summary, list):
                        reasoning = summary[0].get("text", "")
                        break

            return Action(
                action_type=action_type,
                params=params,
                reasoning=reasoning
            )

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse Claude response as JSON: {e}")
            raise ValueError(f"Invalid JSON in Claude response: {e}")
        except Exception as e:
            self.logger.error(f"Error parsing Claude response: {e}")
            raise ValueError(f"Failed to parse Claude response: {e}")

    def format_state(self, state: GUIState) -> Any:
        """
        Format state for Claude agent (returns screenshot bytes).

        Claude expects raw screenshot bytes which it base64-encodes internally.

        Args:
            state: Current GUIState with screenshot

        Returns:
            Screenshot bytes for Claude agent
        """
        return state.screenshot

    def execute(self, sandbox: Any, action: Action) -> Any:
        """Execute Claude Computer Use actions with Claude-specific semantics."""
        self.sandbox = sandbox
        action_type = action.action_type
        args = action.params.copy()

        if action_type == "computer":
            action_type = args["action"]

        if action_type in {"finish", "give_up", "terminate"}:
            return None

        if action_type == "screenshot":
            return None

        if action_type == "wait":
            time.sleep(args.get("duration", 1))
            return None

        if action_type == "mouse_move":
            x, y = args["coordinate"]
            return self.sandbox.execute_command(f"xdotool mousemove {x} {y}")

        if action_type in {"left_click", "right_click", "middle_click", "double_click", "triple_click"}:
            return self._execute_claude_click(action_type, args)

        if action_type == "left_mouse_down":
            return self.sandbox.execute_command("xdotool mousedown 1")

        if action_type == "left_mouse_up":
            return self.sandbox.execute_command("xdotool mouseup 1")

        if action_type == "left_click_drag":
            if "start_coordinate" in args:
                start_x, start_y = args["start_coordinate"]
                end_x, end_y = args["coordinate"]
                return self.sandbox.execute_command(
                    f"xdotool mousemove --sync {start_x} {start_y} mousedown 1 "
                    f"mousemove --sync {end_x} {end_y} mouseup 1"
                )
            if "end_coordinate" in args:
                start_x, start_y = args["coordinate"]
                end_x, end_y = args["end_coordinate"]
                return self.sandbox.execute_command(
                    f"xdotool mousemove --sync {start_x} {start_y} mousedown 1 "
                    f"mousemove --sync {end_x} {end_y} mouseup 1"
                )
            x, y = args["coordinate"]
            return self.sandbox.execute_command(f"xdotool mousedown 1 mousemove --sync {x} {y} mouseup 1")

        if action_type == "scroll":
            return self._execute_claude_scroll(args)

        if action_type == "cursor_position":
            output = self.sandbox.execute_command("xdotool getmouselocation --shell")
            x = int(output.split("X=")[1].split("\n")[0])
            y = int(output.split("Y=")[1].split("\n")[0])
            return f"X={x},Y={y}"

        if action_type == "key":
            return self.sandbox.execute_command(f"xdotool key {args['text']}")

        if action_type == "type":
            return self.sandbox.write(args["text"])

        if action_type == "hold_key":
            escaped_keys = shlex.quote(args["text"])
            return self.sandbox.execute_command(
                f"xdotool keydown {escaped_keys} sleep {args['duration']} keyup {escaped_keys}"
            )

        if action_type == "zoom":
            return self._execute_claude_zoom(args)

        raise ValueError(f"Unknown action type: {action_type}")

    def _execute_claude_click(self, action_type: str, args: dict[str, Any]) -> Any:
        click_buttons = {
            "left_click": "1",
            "right_click": "3",
            "middle_click": "2",
            "double_click": "--repeat 2 --delay 10 1",
            "triple_click": "--repeat 3 --delay 10 1",
        }
        x, y = args["coordinate"]
        command_parts = ["xdotool", f"mousemove --sync {x} {y}"]
        if "key" in args:
            command_parts.append(f"keydown {args['key']}")
        command_parts.append(f"click {click_buttons[action_type]}")
        # Preserve Claude's right-click behavior, which does not release the
        # modifier key after a modified right-click.
        if "key" in args and action_type != "right_click":
            command_parts.append(f"keyup {args['key']}")
        return self.sandbox.execute_command(" ".join(command_parts))

    def _execute_claude_scroll(self, args: dict[str, Any]) -> Any:
        scroll_buttons = {
            "up": 4,
            "down": 5,
            "left": 6,
            "right": 7,
        }
        coordinate = args.get("coordinate")
        mouse_move_part = ""
        if coordinate:
            x, y = coordinate
            mouse_move_part = f"mousemove --sync {x} {y}"
        command_parts = ["xdotool", mouse_move_part]
        modifier_text = args.get("text", "")
        if modifier_text:
            command_parts.append(f"keydown {modifier_text}")
        direction = args.get("direction") or args.get("scroll_direction")
        amount = args.get("scroll_amount", args.get("amount", 1))
        if not direction:
            raise ValueError("scroll action missing 'direction' or 'scroll_direction'")
        command_parts.append(f"click --repeat {amount} {scroll_buttons[direction]}")
        if modifier_text:
            command_parts.append(f"keyup {modifier_text}")
        return self.sandbox.execute_command(" ".join(command_parts))

    def _execute_claude_zoom(self, args: dict[str, Any]) -> bytes:
        region = args.get("region")
        if region is None:
            raise ValueError("zoom action missing 'region'")

        if isinstance(region, dict):
            x0 = int(region.get("x0", region.get("left", 0)))
            y0 = int(region.get("y0", region.get("top", 0)))
            x1 = int(region.get("x1", region.get("right", 0)))
            y1 = int(region.get("y1", region.get("bottom", 0)))
        else:
            if len(region) != 4:
                raise ValueError("zoom region must contain four coordinates")
            x0, y0, x1, y1 = [int(value) for value in region]

        if x1 <= x0 or y1 <= y0:
            raise ValueError("zoom region must define a positive area")

        screenshot = self.sandbox.desktop_screenshot()
        image = Image.open(BytesIO(screenshot))
        width, height = image.size
        crop_box = (
            max(0, min(x0, width)),
            max(0, min(y0, height)),
            max(0, min(x1, width)),
            max(0, min(y1, height)),
        )
        if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
            raise ValueError("zoom region is outside the screenshot bounds")

        cropped = image.crop(crop_box)
        buffer = BytesIO()
        cropped.save(buffer, format="PNG")
        return buffer.getvalue()
