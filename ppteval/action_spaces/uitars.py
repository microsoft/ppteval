"""
UITARS action space for parsing UI-TARS model responses.

Adapts UI-TARS responses into ppteval Action objects.
UI-TARS uses its own grounding action space that needs transformation.

UI-TARS Action Space:
- click(point='<point>x1 y1</point>')
- left_double(point='<point>x1 y1</point>')
- right_single(point='<point>x1 y1</point>')
- drag(start_point='<point>x1 y1</point>', end_point='<point>x2 y2</point>')
- hotkey(key='ctrl c')
- type(content='xxx')
- scroll(point='<point>x1 y1</point>', direction='down/up/right/left')
- wait()
- finished(content='xxx')
"""

import json
import logging
from typing import Any

from ppteval.core.base import Action, GUIState
from ppteval.action_spaces.cua import CUAActionSpace


class UITARSActionSpace(CUAActionSpace):
    """
    Action space for UI-TARS model responses.

    Parses UI-TARS JSON response format and translates grounding actions
    into ppteval Action objects. Note that the UITARS agent already converts
    native action types (left_double, right_single) to CUA-compatible format
    (double_click, right_click) before returning the response.

    This action space handles:
    - finished(content='xxx') -> finish action
    - hotkey(key='ctrl c') -> keypress(keys=['ctrl', 'c'])
    - type(content='xxx') -> type(text='xxx')
    - scroll(direction='down/up') -> scroll(scroll_x=0, scroll_y=±10)
    """

    def __init__(self):
        """Initialize UITARS action space."""
        self.logger = logging.getLogger(__name__)

    def parse_response(self, response: str | dict) -> Action:
        """
        Parse UITARS response into an Action.

        UITARS returns JSON with structure:
        {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"text": "thought process"}]
                },
                {
                    "type": "computer_call",
                    "action": {
                        "type": "click",
                        "x": 100,
                        "y": 200,
                        ...
                    }
                }
            ]
        }

        Or for finish:
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "DONE. Task completed."}]
                }
            ]
        }

        Args:
            response: UITARS response (JSON string or dict)

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

            # Check for finish message
            for item in output:
                if item.get("type") == "message":
                    content = item.get("content", [])
                    if content and isinstance(content, list):
                        text = content[0].get("text", "") if content else ""
                        if "DONE" in text or "finish" in text.lower():
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
                raise ValueError("No 'computer_call' found in UITARS response")

            # Extract action from computer_call
            action_data = computer_call.get("action", {})
            if not action_data:
                raise ValueError("computer_call missing 'action' field")

            action_type = action_data.get("type")
            if not action_type:
                raise ValueError("Action missing 'type' field")

            # Handle finish/finished action (UITARS uses 'finished')
            if action_type == "finish" or action_type == "finished":
                # UITARS finished() action can have 'content' or 'message'
                message = action_data.get("content", "") or action_data.get("text", "") or action_data.get("message", "Task completed")
                return Action(
                    action_type="finish",
                    params={},
                    reasoning=message
                )

            # Copy params (exclude 'type')
            params = {k: v for k, v in action_data.items() if k != "type"}

            # Apply UITARS-specific transformations
            action_type, params = self._transform_uitars_action(action_type, params)

            # Extract reasoning from output
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
            self.logger.error(f"Failed to parse UITARS response as JSON: {e}")
            raise ValueError(f"Invalid JSON in UITARS response: {e}")
        except Exception as e:
            self.logger.error(f"Error parsing UITARS response: {e}")
            raise ValueError(f"Failed to parse UITARS response: {e}")

    def _transform_uitars_action(self, action_type: str, params: dict) -> tuple[str, dict]:
        """
        Transform UITARS action types and parameters to ppteval format.

        Note: The UITARS agent already converts native action types to CUA-compatible:
        - left_double -> double_click
        - right_single -> right_click
        - hotkey -> keypress

        This method handles parameter transformations:
        - content -> text (for type action)
        - key -> keys (for keypress action, split by spaces)
        - direction -> scroll_x/scroll_y (for scroll action)

        Args:
            action_type: UITARS action type (may be pre-converted to CUA format)
            params: UITARS action parameters

        Returns:
            Tuple of (transformed_action_type, transformed_params)
        """
        params = params.copy()  # Don't modify original

        # Handle keypress (converted from hotkey by agent)
        if action_type == "keypress":
            # UITARS 'key' param needs to be split and converted to 'keys' list
            if "key" in params:
                key_str = params.pop("key")
                # Split by spaces (e.g., "ctrl c" -> ["ctrl", "c"])
                params["keys"] = key_str.strip().split()

        # Handle type action
        elif action_type == "type":
            # UITARS uses 'content' but screenenv uses 'text'
            if "content" in params:
                params["text"] = params.pop("content")

        # Handle scroll action
        elif action_type == "scroll":
            # UITARS uses 'direction', need to convert to scroll_x/scroll_y
            if "direction" in params:
                direction = params.pop("direction")
                SCROLL_STEP = 10  # Match UITARS agent default

                if direction == "down":
                    params["scroll_y"] = SCROLL_STEP
                    params["scroll_x"] = 0
                elif direction == "up":
                    params["scroll_y"] = -SCROLL_STEP
                    params["scroll_x"] = 0
                elif direction == "right":
                    params["scroll_x"] = SCROLL_STEP
                    params["scroll_y"] = 0
                elif direction == "left":
                    params["scroll_x"] = -SCROLL_STEP
                    params["scroll_y"] = 0

        # Handle drag action
        elif action_type == "drag":
            # UITARS agent already converts to path format with x, y
            # If path exists, convert to fr/to tuples
            if "path" in params:
                path = params.pop("path")
                if len(path) >= 2:
                    params["fr"] = (path[0]["x"], path[0]["y"])
                    params["to"] = (path[-1]["x"], path[-1]["y"])

        return action_type, params

    def format_state(self, state: GUIState) -> Any:
        """
        Format state for UITARS agent (returns screenshot bytes).

        UITARS expects raw screenshot bytes which it base64-encodes internally.

        Args:
            state: Current GUIState with screenshot

        Returns:
            Screenshot bytes for UITARS agent
        """
        return state.screenshot

