"""OpenCUA action space for ppteval."""

import json
import logging
import re
import time
import traceback
from typing import Any

from ppteval.core.base import Action, GUIState
from ppteval.action_spaces.screenenv import BaseScreenEnvActionSpace
from ppteval.action_spaces.opencua_utils import project_coordinate_to_absolute_scale


def parse_response_to_cot_and_action(
    input_string: str,
    screen_size: tuple[int, int],
    coordinate_type: str,
) -> tuple[str, list[str], dict[str, Any]]:
    """Parse raw OpenCUA model output into reasoning sections and low-level actions."""
    sections: dict[str, Any] = {}

    try:
        obs_match = re.search(
            r"^(?:##\s*)?Observation\s*:?[\n\r]+(.*?)(?=^(?:##\s*)?Thought:|^(?:##\s*)?Action:|^##|\Z)",
            input_string,
            re.DOTALL | re.MULTILINE,
        )
        if obs_match:
            sections["observation"] = obs_match.group(1).strip()

        thought_match = re.search(
            r"^(?:##\s*)?Thought\s*:?[\n\r]+(.*?)(?=^(?:##\s*)?Action:|^##|\Z)",
            input_string,
            re.DOTALL | re.MULTILINE,
        )
        if thought_match:
            sections["thought"] = thought_match.group(1).strip()

        action_match = re.search(
            r"^(?:##\s*)?Action\s*:?[\n\r]+(.*?)(?=^##|^```|\Z)",
            input_string,
            re.DOTALL | re.MULTILINE,
        )
        if action_match:
            sections["action"] = action_match.group(1).strip()

        code_blocks = re.findall(r"```(?:code|python)?\s*(.*?)\s*```", input_string, re.DOTALL | re.IGNORECASE)
        if not code_blocks:
            return f"<Error>: no code blocks found in the input string: {input_string}", ["FAIL"], sections

        code_block = code_blocks[-1].strip()
        code_block = re.sub(r"\bcomputer\.triple_click\b", "pyautogui.tripleClick", code_block)
        sections["original_code"] = code_block

        if "computer.wait" in code_block.lower():
            sections["code"] = "WAIT"
            return sections.get("action", "Wait for operation to complete"), ["WAIT"], sections

        if "computer.terminate" in code_block.lower():
            lower_block = code_block.lower()
            if "failure" in lower_block or "fail" in lower_block:
                sections["code"] = "FAIL"
                return code_block, ["FAIL"], sections
            if "success" in lower_block:
                sections["code"] = "DONE"
                return code_block, ["DONE"], sections
            return f"<Error>: terminate action found but no status provided: {input_string}", ["FAIL"], sections

        sections["code"] = project_coordinate_to_absolute_scale(
            code_block,
            screen_width=screen_size[0],
            screen_height=screen_size[1],
            coordinate_type=coordinate_type,
        )

        if not sections.get("code") or not sections.get("action"):
            return f"<Error>: no code parsed: {input_string}", ["FAIL"], sections

        return sections["action"], [sections["code"]], sections

    except Exception as e:
        error_message = f"<Error>: parsing response: {str(e)}\nTraceback:\n{traceback.format_exc()}\nInput string: {input_string}"
        return error_message, ["FAIL"], sections


class OpenCUAActionSpace(BaseScreenEnvActionSpace):
    """Parse native OpenCUA JSON output into ppteval actions."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_response(self, response: str | dict) -> Action:
        """Parse OpenCUA response JSON into an Action."""
        try:
            response_data = json.loads(response) if isinstance(response, str) else response
            output = response_data.get("output", [])

            reasoning = None
            for item in output:
                if item.get("type") == "reasoning":
                    summary = item.get("summary", [])
                    if summary and isinstance(summary, list):
                        reasoning = summary[0].get("text", "")
                        break

            for item in output:
                if item.get("type") == "message":
                    content = item.get("content", [])
                    text = content[0].get("text", "") if content else ""
                    if "DONE" in text:
                        return Action(action_type="finish", params={}, reasoning=text)

            for item in output:
                if item.get("type") != "computer_call":
                    continue

                action_data = item.get("action", {})
                action_type = action_data.get("type")
                if not action_type:
                    raise ValueError("OpenCUA computer_call missing action type")

                if action_type == "finish":
                    return Action(
                        action_type="finish",
                        params={},
                        reasoning=action_data.get("message", "Task completed"),
                    )

                params = {key: value for key, value in action_data.items() if key != "type"}
                if action_type == "wait" and "duration" in params:
                    params["time"] = params.pop("duration")
                return Action(action_type=action_type, params=params, reasoning=reasoning)

            raise ValueError("No 'computer_call' found in OpenCUA response")
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse OpenCUA response as JSON: {e}")
            raise ValueError(f"Invalid JSON in OpenCUA response: {e}")
        except Exception as e:
            self.logger.error(f"Error parsing OpenCUA response: {e}")
            raise ValueError(f"Failed to parse OpenCUA response: {e}")

    def format_state(self, state: GUIState) -> Any:
        """Format GUI state for OpenCUA."""
        return state.screenshot

    def execute(self, sandbox: Any, action: Action) -> Any:
        """Execute OpenCUA actions with OpenCUA-specific semantics."""
        self.sandbox = sandbox
        action_type = action.action_type
        args = action.params.copy()

        if action_type == "computer":
            action_type = args.pop("action")

        if action_type in {"finish", "give_up", "terminate"}:
            return None

        if action_type == "screenshot":
            return None

        if action_type == "wait":
            duration = args.get("time", args.get("duration", 20))
            time.sleep(duration)
            return f"Waited for {duration} seconds"

        if action_type == "pyautogui":
            code = args.get("code", "")
            if code:
                return self._execute_pyautogui_code(code)
            return None

        return self._dispatch_screenenv(action_type, args)
