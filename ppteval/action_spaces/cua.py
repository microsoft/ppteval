"""
CUA (Computer Use Agent) action space.

Adapts OpenAI Computer Use Agent responses into ppteval Action objects.
Includes CUA-specific action transformations and parameter mappings.
"""

import json
import logging
from typing import Any

from ppteval.core.base import Action, GUIState
from ppteval.action_spaces.screenenv import BaseScreenEnvActionSpace


class CUAActionSpace(BaseScreenEnvActionSpace):
    """
    Action space for OpenAI Computer Use Agent (CUA) responses.

    Parses CUA's JSON response format with "computer_call" actions
    and translates them into ppteval Action objects.

    Includes CUA-specific action transformations:
    - click -> left_click/right_click/middle_click
    - type -> write
    - keypress -> press (with keys param)
    - move -> move_mouse
    - scroll -> scroll with direction or scroll_x/scroll_y
    - drag -> drag with path conversion
    - wait -> wait with duration (seconds -> milliseconds)
    """

    def __init__(self):
        """Initialize CUA action space."""
        self.logger = logging.getLogger(__name__)

    def parse_response(self, response: str | dict) -> Action:
        """
        Parse CUA response into an Action.

        CUA returns JSON with structure:
        {
            "output": [
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",  # or other action types
                        "x": 100,
                        "y": 200,
                        ...other params...
                    }
                },
                {
                    "type": "message",
                    "content": [{"text": "DONE. Task completed."}]
                }
            ]
        }

        Args:
            response: CUA response (JSON string or dict)

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

            # Check for user interaction (requires human input)
            for item in output:
                if item.get("type") == "user_interaction":
                    self.logger.warning("Agent requires user input")
                    return Action(
                        action_type="give_up",
                        params={},
                        reasoning="Agent requires user input"
                    )

            # Check for finish message ("DONE" in message content)
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

            # Find computer_call action
            computer_call = None
            for item in output:
                if item.get("type") == "computer_call":
                    computer_call = item
                    break

            if not computer_call:
                # Check for explicit finish call (alternative format)
                for item in output:
                    if item.get("type") == "call" and item.get("action", {}).get("type") == "finish":
                        message = item["action"].get("message", "Task completed")
                        return Action(
                            action_type="finish",
                            params={},
                            reasoning=message
                        )

                # No actionable computer_call found
                raise ValueError("No 'computer_call' found in CUA response")

            # Extract action from computer_call
            action_data = computer_call.get("action", {})
            if not action_data:
                raise ValueError("computer_call missing 'action' field")

            action_type = action_data.get("type")
            if not action_type:
                raise ValueError("Action missing 'type' field")

            # Handle finish action
            if action_type == "finish":
                return Action(
                    action_type="finish",
                    params={},
                    reasoning=action_data.get("message", "Task completed")
                )

            # Copy params (exclude 'type' since it's the action_type)
            params = {k: v for k, v in action_data.items() if k != "type"}

            # Extract reasoning if present
            reasoning = None

            # First check for reasoning_trace (OpenAI Responses API)
            reasoning_trace = response_data.get("reasoning_trace")
            if reasoning_trace and isinstance(reasoning_trace, list):
                # Combine all reasoning trace items
                trace_parts = []
                for trace_item in reasoning_trace:
                    if isinstance(trace_item, dict):
                        trace_text = trace_item.get("text", "")
                        if trace_text:
                            trace_parts.append(trace_text)
                if trace_parts:
                    reasoning = "\n".join(trace_parts)

            # If no reasoning trace, check for message blocks
            if not reasoning:
                for item in output:
                    if item.get("type") == "message":
                        content = item.get("content", [])
                        if content and isinstance(content, list):
                            reasoning = content[0].get("text", "")
                        break

            return Action(
                action_type=action_type,
                params=params,
                reasoning=reasoning
            )

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse CUA response as JSON: {e}")
            raise ValueError(f"Invalid JSON in CUA response: {e}")
        except Exception as e:
            self.logger.error(f"Error parsing CUA response: {e}")
            raise ValueError(f"Failed to parse CUA response: {e}")

    def format_state(self, state: GUIState) -> Any:
        """
        Format state for CUA agent (returns screenshot bytes).

        CUA expects raw screenshot bytes which it base64-encodes internally.

        Args:
            state: Current GUIState with screenshot

        Returns:
            Screenshot bytes for CUA agent
        """
        return state.screenshot

    def _execute_single(self, sandbox: Any, action: Action) -> Any:
        """Execute a single CUA action with CUA-specific ScreenEnv semantics."""
        self.sandbox = sandbox
        action_type = action.action_type
        args = action.params.copy()

        if action_type == "computer":
            action_type = args.pop("action")

        if action_type in {"finish", "give_up", "terminate"}:
            return None

        if action_type == "click":
            button = args.pop("button", "left")
            return self._dispatch_screenenv(f"{button}_click", args)

        if action_type == "type":
            return self.sandbox.write(**args)

        if action_type == "keypress":
            args["key"] = args.pop("keys")
            return self.sandbox.press(**args)

        if action_type == "move":
            action_type = "move_mouse"

        if action_type == "scroll":
            return self._execute_cua_scroll(args)

        if action_type == "wait":
            return self._execute_cua_wait(args)

        if action_type == "drag":
            return self._execute_cua_drag(args)

        return self._dispatch_screenenv(action_type, args)

    def _execute_cua_scroll(self, args: dict[str, Any]) -> Any:
        """Execute CUA scroll actions."""
        if "x" in args and "y" in args:
            self.sandbox.move_mouse(x=args.pop("x"), y=args.pop("y"))

        if "direction" in args:
            self.sandbox.scroll(direction=args["direction"], amount=args.get("amount", 1))
            return None

        scroll_y = args.get("scroll_y", 0)
        if scroll_y != 0:
            button = 4 if scroll_y < 0 else 5
            clicks = abs(scroll_y)
            self.sandbox.execute_command(f"xdotool click --repeat {int(str(clicks)[0])} {button}")

        scroll_x = args.get("scroll_x", 0)
        if scroll_x != 0:
            button = 6 if scroll_x < 0 else 7
            clicks = abs(scroll_x)
            self.sandbox.execute_command(f"xdotool click --repeat {int(str(clicks)[0])} {button}")
        return None

    def _execute_cua_wait(self, args: dict[str, Any]) -> Any:
        if "duration" in args:
            duration = int(args["duration"] * 1000)
        elif "ms" in args:
            duration = args["ms"]
        else:
            duration = 5000
        return self.sandbox.wait(duration)

    def _execute_cua_drag(self, args: dict[str, Any]) -> Any:
        if "path" in args:
            path = args["path"]
            if len(path) >= 2:
                fr = (path[0]["x"], path[0]["y"])
                to = (path[-1]["x"], path[-1]["y"])
                return self.sandbox.drag(fr, to)
            return None
        return self.sandbox.drag(**args)
