"""
Qwen3-VL action space for parsing Qwen3-VL model responses.

Adapts Qwen3-VL responses into ppteval Action objects.
Qwen3-VL uses tool-call based action space with pyautogui-style actions.

Qwen3-VL Action Space:
- left_click(coordinate=[x, y])
- right_click(coordinate=[x, y])
- middle_click(coordinate=[x, y])
- double_click(coordinate=[x, y])
- mouse_move(coordinate=[x, y])
- left_click_drag(coordinate=[x, y])
- key(keys=['key1', 'key2'])
- type(text='xxx')
- scroll(pixels=N)
- hscroll(pixels=N)
- wait(time=N)
- terminate(status='success'|'failure')
"""

import json
import logging
import time
from typing import Any

from ppteval.action_spaces.screenenv import BaseScreenEnvActionSpace
from ppteval.core.base import Action, GUIState


class Qwen3VLActionSpace(BaseScreenEnvActionSpace):
    """
    Action space for Qwen3-VL model responses.

    Parses Qwen3-VL JSON response format and translates tool-call actions
    into ppteval Action objects.

    This action space handles:
    - terminate(status='success') -> finish action
    - key(keys=['ctrl', 'c']) -> keypress(keys=['ctrl', 'c'])
    - type(text='xxx') -> type(text='xxx')
    - scroll(pixels=N) -> scroll(scroll_y=N)
    - hscroll(pixels=N) -> scroll(scroll_x=N)
    - left_click_drag(coordinate=[x, y]) -> drag action
    """

    def __init__(self):
        """Initialize Qwen3VL action space."""
        self.logger = logging.getLogger(__name__)
        # Map PyAutoGUI key names to xdotool-compatible key names
        self._KEY_MAP = {
            # Basic controls
            "enter": "Return",
            "return": "Return",
            "esc": "Escape",
            "escape": "Escape",
            "backspace": "BackSpace",
            "tab": "Tab",
            "space": "space",
            # Arrows
            "left": "Left",
            "right": "Right",
            "up": "Up",
            "down": "Down",
            # Navigation
            "home": "Home",
            "end": "End",
            "insert": "Insert",
            "delete": "Delete",
            "del": "Delete",
            "pageup": "Page_Up",
            "pgup": "Page_Up",
            "pagedown": "Page_Down",
            "pgdn": "Page_Down",
            # Locks
            "capslock": "Caps_Lock",
            "numlock": "Num_Lock",
            "scrolllock": "Scroll_Lock",
            # PrintScreen and pause
            "printscreen": "Print",
            "prntscrn": "Print",
            "prtsc": "Print",
            "prtscr": "Print",
            "print": "Print",
            "pause": "Pause",
            # Modifiers
            "shift": "shift",
            "shiftleft": "shift",
            "shiftright": "shift",
            "ctrl": "ctrl",
            "control": "ctrl",
            "ctrlleft": "ctrl",
            "ctrlright": "ctrl",
            "alt": "alt",
            "altleft": "alt",
            "altright": "alt",
            "win": "super",
            "winleft": "super",
            "winright": "super",
            "command": "super",
            "option": "alt",
            "optionleft": "alt",
            "optionright": "alt",
            # Menu key
            "menu": "Menu",
            "apps": "Menu",
            # Volume/media (common X names)
            "volumedown": "XF86AudioLowerVolume",
            "volumeup": "XF86AudioRaiseVolume",
            "volumemute": "XF86AudioMute",
            "playpause": "XF86AudioPlay",
            "nexttrack": "XF86AudioNext",
            "prevtrack": "XF86AudioPrev",
            "stop": "XF86AudioStop",
        }
        # Modifier keys that indicate a chord (require lowercase letter keys)
        self._MODIFIER_KEYS = {"ctrl", "alt", "shift", "super", "meta", "win", "command", "option"}

    def _map_key_token(self, token: str, lowercase_letters: bool = False) -> str:
        """
        Map a single PyAutoGUI-style key token to xdotool-compatible name.

        Args:
            token: The key token to map.
            lowercase_letters: If True, lowercase single letter keys (for use in chords
                               like ctrl+v where uppercase would imply shift).
        """
        if not isinstance(token, str):
            return str(token)
        t = token.strip().strip("'\"").lower()
        # Function keys f1..f24
        if len(t) >= 2 and t[0] == "f" and t[1:].isdigit():
            try:
                num = int(t[1:])
                if 1 <= num <= 24:
                    return f"F{num}"
            except ValueError:
                pass
        # Map via dictionary
        mapped = self._KEY_MAP.get(t)
        if mapped:
            return mapped
        # Single letter keys: lowercase if in a modifier chord
        if lowercase_letters and len(t) == 1 and t.isalpha():
            return t.lower()
        # Single letters/digits and common punctuation: return as-is
        return token

    def _map_keys(self, keys: list[str], lowercase_letters: bool = False) -> list[str]:
        """Map a list of key tokens to xdotool-compatible names."""
        return [self._map_key_token(k, lowercase_letters=lowercase_letters) for k in keys]

    def _clean_key_list(self, keys: list[Any]) -> list[str]:
        cleaned_keys = []
        for key in keys:
            if isinstance(key, str):
                key = key.strip()
                if key.startswith("keys=["):
                    key = key[6:]
                if key.endswith("]"):
                    key = key[:-1]
                if key.startswith("['") or key.startswith('["'):
                    key = key[2:] if len(key) > 2 else key
                if key.endswith("']") or key.endswith('"]'):
                    key = key[:-2] if len(key) > 2 else key
                key = key.strip().strip("'\"")
                if key:
                    cleaned_keys.append(key)
            else:
                cleaned_keys.append(str(key))
        return cleaned_keys

    def _map_key_chord_text(self, text: str) -> str:
        if not isinstance(text, str):
            return str(text)
        if "+" in text:
            parts = [part.strip() for part in text.split("+") if part.strip()]
            has_modifier = any(part.lower() in self._MODIFIER_KEYS for part in parts)
            return "+".join(self._map_keys(parts, lowercase_letters=has_modifier))
        return self._map_key_token(text)

    def parse_response(self, response: str | dict) -> Action:
        """
        Parse Qwen3-VL response into an Action.

        Qwen3-VL returns JSON with structure:
        {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"text": "thought process"}]
                },
                {
                    "type": "computer_call",
                    "action": {
                        "type": "left_click",
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
            response: Qwen3-VL response (JSON string or dict)

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
                        if "DONE" in text or "finish" in text.lower() or "terminate" in text.lower():
                            return Action(action_type="finish", params={}, reasoning=text)

            # Extract reasoning from output
            reasoning = None
            for item in output:
                if item.get("type") == "reasoning":
                    summary = item.get("summary", [])
                    if summary and isinstance(summary, list):
                        reasoning = summary[0].get("text", "")
                        break

            computer_calls = [item for item in output if item.get("type") == "computer_call"]
            if not computer_calls:
                raise ValueError("No 'computer_call' found in Qwen3-VL response")

            action_items = []
            for computer_call in computer_calls:
                action_data = computer_call.get("action", {})
                if not action_data:
                    raise ValueError("computer_call missing 'action' field")
                if isinstance(action_data, list):
                    action_items.extend(action_data)
                else:
                    action_items.append(action_data)

            parsed_actions = [self._parse_single_qwen_action(action_data, reasoning) for action_data in action_items]
            if len(parsed_actions) == 1:
                return parsed_actions[0]

            return Action(action_type="multi_action", params={"actions": parsed_actions}, reasoning=reasoning)

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse Qwen3-VL response as JSON: {e}")
            raise ValueError(f"Invalid JSON in Qwen3-VL response: {e}")
        except Exception as e:
            self.logger.error(f"Error parsing Qwen3-VL response: {e}")
            raise ValueError(f"Failed to parse Qwen3-VL response: {e}")

    def _transform_qwen3vl_action(self, action_type: str, params: dict) -> tuple[str, dict]:
        """
        Deprecated compatibility shim.

        Qwen3-VL uses the OSWorld action space. Execution-time details such as
        xdotool key mapping, scroll direction, and pointer actions are handled
        by this action space's ``execute`` method.
        """
        return action_type, params

    def _parse_single_qwen_action(self, action_data: dict[str, Any], reasoning: str | None) -> Action:
        action_type = action_data.get("type")
        if not action_type:
            raise ValueError("Action missing 'type' field")

        if action_type == "terminate":
            status = action_data.get("status", "success")
            return Action(action_type="finish", params={"status": status}, reasoning=f"Task terminated with status: {status}")

        params = {k: v for k, v in action_data.items() if k != "type"}
        return Action(action_type=action_type, params=params, reasoning=reasoning)

    def format_state(self, state: GUIState) -> Any:
        """
        Format state for Qwen3-VL agent (returns screenshot bytes).

        Qwen3-VL expects raw screenshot bytes which it processes internally.

        Args:
            state: Current GUIState with screenshot

        Returns:
            Screenshot bytes for Qwen3-VL agent
        """
        return state.screenshot

    def execute(self, sandbox: Any, action: Action) -> Any:
        """Execute Qwen3-VL OSWorld actions with Qwen-specific semantics."""
        self.sandbox = sandbox
        action_type = action.action_type
        args = action.params.copy()

        if action_type == "computer":
            action_type = args["action"]

        if action_type == "multi_action":
            results = []
            for child_action in args["actions"]:
                results.append(self.execute(sandbox, child_action))
            return results

        if action_type == "screenshot":
            return None

        if action_type == "wait":
            duration = args.get("time", args.get("duration", 1))
            time.sleep(duration)
            return None

        if action_type == "mouse_move":
            x, y = args["coordinate"]
            return self.sandbox.execute_command(f"xdotool mousemove {x} {y}")

        if action_type in {"left_click", "right_click", "middle_click", "double_click", "triple_click"}:
            return self._execute_qwen_click(action_type, args)

        if action_type == "left_click_drag":
            x, y = args["coordinate"]
            return self.sandbox.execute_command(f"xdotool mousedown 1 mousemove --sync {x} {y} mouseup 1")

        if action_type == "scroll":
            return self._execute_qwen_scroll(args, horizontal=False)

        if action_type == "hscroll":
            return self._execute_qwen_scroll(args, horizontal=True)

        if action_type == "key":
            return self._execute_qwen_key(args)

        if action_type == "type":
            if args.get("keys"):
                self._execute_qwen_key({"keys": args["keys"]})
            text = args.get("text", "")
            if text:
                return self.sandbox.write(text)
            return None

        if action_type in {"terminate", "finish", "give_up"}:
            return None

        raise ValueError(f"Unknown action type: {action_type}")

    def _execute_qwen_click(self, action_type: str, args: dict[str, Any]) -> Any:
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
            keyname = self._map_key_chord_text(args["key"])
            command_parts.append(f"keydown {keyname}")
        command_parts.append(f"click {click_buttons[action_type]}")
        if "key" in args:
            keyname = self._map_key_chord_text(args["key"])
            command_parts.append(f"keyup {keyname}")
        return self.sandbox.execute_command(" ".join(command_parts))

    def _execute_qwen_scroll(self, args: dict[str, Any], horizontal: bool) -> Any:
        scroll_buttons = {
            "up": 4,
            "down": 5,
            "left": 6,
            "right": 7,
        }
        coordinate = args.get("coordinate")
        command_parts = ["xdotool"]
        if coordinate:
            x, y = coordinate
            command_parts.append(f"mousemove --sync {x} {y}")

        pixels = args.get("pixels", 0)
        if pixels != 0:
            if horizontal:
                direction = "right" if pixels > 0 else "left"
            else:
                direction = "down" if pixels < 0 else "up"
            amount = abs(pixels)
        else:
            direction = args.get("direction") or args.get("scroll_direction", "right" if horizontal else "down")
            amount = args.get("scroll_amount", args.get("amount", 1))
        command_parts.append(f"click --repeat {amount} {scroll_buttons[direction]}")
        return self.sandbox.execute_command(" ".join(command_parts))

    def _execute_qwen_key(self, args: dict[str, Any]) -> Any:
        keys = args.get("keys", [])
        if isinstance(keys, list) and keys:
            cleaned_keys = self._clean_key_list(keys)
            if not cleaned_keys:
                return None
            has_modifier = any(k.lower() in self._MODIFIER_KEYS for k in cleaned_keys)
            key_text = "+".join(self._map_keys(cleaned_keys, lowercase_letters=has_modifier))
        else:
            key_text = self._map_key_chord_text(args.get("text", ""))

        if key_text:
            return self.sandbox.execute_command(f"xdotool key {key_text}")
        return None
