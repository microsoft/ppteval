"""
UI-TARS Agent for ppteval.

Self-contained UI-TARS agent implementation with ppteval Agent interface.
Supports loading configuration from YAML files.
"""

import re
import json
import codecs
import base64
import logging
import requests
import time
import random
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from ppteval.core.base import Agent, Action, State, GUIState
from ppteval.action_spaces import UITARSActionSpace
from ppteval.config import UITARSConfig


# Source: https://github.com/bytedance/UI-TARS/blob/main/codes/ui_tars/prompt.py
UI_TARS_INSTRUCTION = Template("""You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task. When you are done with the task (or have tried and found you cannot complete it), you must explicitly communicate so through finished() action.

## Output Format
```
Thought: ...
Action: ...
```

## Action Space

click(start_box='<|box_start|>(x1,y1)<|box_end|>')
left_double(start_box='<|box_start|>(x1,y1)<|box_end|>')
right_single(start_box='<|box_start|>(x1,y1)<|box_end|>')
drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x3,y3)<|box_end|>')
hotkey(key='')
type(content='xxx') # Use escape characters \\', \\\", and \\n in content part to ensure we can parse the content in normal python string format. If you want to submit your input, use \\n at the end of content.
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', direction='down or up or right or left')
wait() #Sleep for 5s and take a screenshot to check for any changes.
finished(content='xxx') # Use escape characters \\', \\", and \\n in content part to ensure we can parse the content in normal python string format.


## Note
- Use English in `Thought` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `Thought` part.

## User Instruction
${instruction}
""")

SCROLL_STEP = 10  # a fix amount to scroll everytime


class UITARSAgent(Agent):
    """
    PPTEval agent for UI-TARS model.

    Integrates UI-TARS HTTP API with ppteval's Agent interface.
    Can load configuration from YAML file or accept dict/UITARSConfig directly.
    """

    def __init__(self, config: dict[str, Any] | UITARSConfig | str | Path | None = None):
        """
        Initialize UITARS agent with configuration.

        Args:
            config: One of:
                - Path/str to YAML config file
                - Configuration dict
                - UITARSConfig object
                - None (uses default config from ppteval/configs/uitars.yaml)
        """
        self.logger = logging.getLogger(__name__)

        # Load configuration
        if config is None:
            # Load default config
            config_path = Path(__file__).parent.parent / "configs" / "uitars.yaml"
            if config_path.exists():
                self.agent_config = self._load_yaml_config(config_path)
            else:
                self.agent_config = UITARSConfig()
        elif isinstance(config, (str, Path)):
            # Load from YAML file
            self.agent_config = self._load_yaml_config(Path(config))
        elif isinstance(config, dict):
            self.agent_config = UITARSConfig(**config)
        elif isinstance(config, UITARSConfig):
            self.agent_config = config
        else:
            raise ValueError(f"Config must be dict, UITARSConfig, Path, or None, got {type(config)}")
        self.action_space = UITARSActionSpace()

        # Store instruction for multi-step interactions
        self.instruction: str | None = None

        # Extract configuration values
        self.endpoint_url = self.agent_config.endpoint_url
        self.token = self.agent_config.token

        self.headers = {'Authorization': f'Bearer {self.token}'}
        self.history_screenshots: List[str] = []  # base64 strings
        self.history_responses: List[str] = []

        self.logger.info(f"Initialized UITARS agent with endpoint: {self.endpoint_url}")

    @staticmethod
    def _load_yaml_config(path: Path) -> UITARSConfig:
        """Load UITARSConfig from YAML file."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        return UITARSConfig(**data)

    def _make_request_with_retry(self, endpoint_url: str, headers: dict, files: list) -> requests.Response:
        """
        Make a request with retry logic for 429 errors using exponential backoff.

        Args:
            endpoint_url: The URL to make the request to
            headers: Request headers
            files: Files to send in the request

        Returns:
            requests.Response: The successful response

        Raises:
            Exception: If all retries are exhausted or non-retryable error occurs
        """
        max_retries = self.agent_config.max_retries
        base_delay = 1.0  # Start with 1 second delay

        for attempt in range(max_retries + 1):  # +1 to include the initial attempt
            try:
                response = requests.post(endpoint_url, headers=headers, files=files,
                                       timeout=self.agent_config.timeout_seconds)

                # If successful or non-retryable error, return immediately
                if response.status_code != 429:
                    return response

                # If this is a 429 and we've exhausted retries, raise
                if attempt == max_retries:
                    raise Exception(f"UI-TARS request failed with status 429 after {max_retries} retries: {response.text}")

                # Calculate delay with exponential backoff and jitter
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)

                self.logger.warning(f"Rate limit hit (429), retrying in {delay:.2f} seconds (attempt {attempt + 1}/{max_retries + 1})")
                time.sleep(delay)

            except requests.exceptions.Timeout:
                if attempt == max_retries:
                    raise Exception(f"UI-TARS request timed out after {max_retries} retries")

                # Retry on timeout as well
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                self.logger.warning(f"Request timed out, retrying in {delay:.2f} seconds (attempt {attempt + 1}/{max_retries + 1})")
                time.sleep(delay)

            except requests.exceptions.RequestException as e:
                # For other request exceptions, don't retry
                raise Exception(f"UI-TARS request failed with network error: {str(e)}")

        # This should never be reached, but just in case
        raise Exception("Unexpected error in retry logic")

    def _parse_action(self, action_str: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Parses the model's response to extract the action and its arguments.
        """
        action_type = action_str.split('(')[0]
        action_args = {}

        # Look for all occurrences of hotkey(key='...') in action_str
        hotkey_pattern = r"hotkey\(key='([^']*)'\)"
        hotkey_matches = re.findall(hotkey_pattern, action_str)
        if hotkey_matches:
            action_args['keys'] = []
            for key_str in hotkey_matches:
                cleaned_value = key_str.strip()
                action_args['keys'].append(cleaned_value.split())

            if len(action_args['keys']) == 1:
                action_args['keys'] = action_args['keys'][0]
        else:
            # Extract arguments between parentheses
            if '(' in action_str and ')' in action_str:
                args_text = action_str[action_str.find('(')+1:action_str.rfind(')')]

                # Split arguments by comma, handling nested quotes
                args = []
                current_arg = ""
                in_quotes = False
                for char in args_text:
                    if char == "'" and not in_quotes:
                        in_quotes = True
                    elif char == "'" and in_quotes:
                        in_quotes = False
                    elif char == ',' and not in_quotes:
                        args.append(current_arg.strip())
                        current_arg = ""
                    else:
                        current_arg += char
                if current_arg:
                    args.append(current_arg.strip())

                # Parse each argument
                for arg in args:
                    if '=' in arg:
                        key, value = arg.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip("'")

                        if key == 'start_box':
                            # Remove parentheses and split coordinates
                            coords = value.strip('()')
                            x, y = coords.split(',')
                            action_args['x'] = int(x)
                            action_args['y'] = int(y)
                        elif key == 'end_box':
                            # Remove parentheses and split coordinates
                            coords = value.strip('()')
                            x, y = coords.split(',')
                            # drag actions, create a path with start and end points
                            if 'x' in action_args and 'y' in action_args:
                                action_args['path'] = [
                                    {"x": action_args['x'], "y": action_args['y']},
                                    {"x": int(x), "y": int(y)}
                                ]
                                # Remove the individual x,y coordinates since we now have them in path
                                del action_args['x']
                                del action_args['y']
                        elif key == 'direction':
                            # Convert direction to scroll_x and scroll_y for VNC
                            if value == 'down': action_args.update({'scroll_y': SCROLL_STEP, 'scroll_x': 0})
                            elif value == 'up': action_args.update({'scroll_y': -SCROLL_STEP, 'scroll_x': 0})
                            elif value == 'right': action_args.update({'scroll_x': SCROLL_STEP, 'scroll_y': 0})
                            elif value == 'left': action_args.update({'scroll_x': -SCROLL_STEP, 'scroll_y': 0})
                        elif key == 'content':
                            action_args['text'] = codecs.decode(value.strip(), 'unicode_escape')
                        elif key == 'key':
                            # Clean up the value before splitting
                            cleaned_value = value.strip()
                            action_args['keys'] = cleaned_value.split()

        # UI-TARS and CUA action equivalency
        uitars2cua_actions = {
            'left_double': 'double_click',
            'right_single': 'right_click',
            'hotkey': 'keypress'
        }
        for uitars_action, cua_action in uitars2cua_actions.items():
            if action_type == uitars_action:
                action_type = cua_action

        return action_type, action_args

    def step(self, state: State) -> Action:
        """
        Take a step given the current state.

        Args:
            state: Current GUIState with screenshot

        Returns:
            Action to execute in the environment

        Raises:
            ValueError: If state is not a GUIState or instruction not set
        """
        if not isinstance(state, GUIState):
            raise ValueError(f"UITARS requires GUIState, got {type(state)}")

        if self.instruction is None:
            raise ValueError("Instruction not set. Call set_instruction() first.")

        # Format state for UITARS agent (get screenshot bytes)
        screenshot = self.action_space.format_state(state)

        # Prepare the files for the request
        prompt = UI_TARS_INSTRUCTION.substitute(instruction=self.instruction)
        screenshot_b64 = base64.b64encode(screenshot).decode("utf-8")
        files = [
            ('user_prompt', ('prompt.txt', prompt, 'text/plain')),
            ('cur_screenshot', ('current_screenshot.png', screenshot_b64, 'text/plain')),
        ]

        # Add history if available
        for i, (hist_screenshot, hist_response) in enumerate(zip(self.history_screenshots, self.history_responses)):
            files.append((f'history_screenshot_{i}', (f'history_screenshot_{i}.png', hist_screenshot, 'text/plain')))
            files.append((f'history_response_{i}', (f'history_response_{i}.txt', hist_response, 'text/plain')))

        # Log what we're sending to UITARS
        print(f"  UITARS Request:")
        print(f"    Instruction: {self.instruction[:100]}...")
        print(f"    Current screenshot: <screenshot bytes>")
        print(f"    History items sent: {len(self.history_screenshots)} screenshots + {len(self.history_responses)} responses")
        print(f"    Total files in request: {len(files)} (2 current + {len(self.history_screenshots)*2} history)")
        if self.history_responses:
            print(f"    Last response (truncated): {self.history_responses[-1][:150]}...")

        # Make the request with retry logic for 429 errors
        response = self._make_request_with_retry(self.endpoint_url, self.headers, files)

        if response.status_code != 200:
            raise Exception(f"UI-TARS request failed with status {response.status_code}: {response.text}")

        response_text = response.text.strip()

        # Store in history
        self.history_screenshots.append(screenshot_b64)
        self.history_responses.append(response_text)

        # Parse response and format for ppteval
        thought_match = re.search(r"Thought: (.+?)(?=\s*Action: |$)", response_text, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else ""

        action_match = re.search(r"Action: (.+?)(?=\s*$)", response_text, re.DOTALL)
        action_str = action_match.group(1).strip()

        action_type, action_args = self._parse_action(action_str)

        if not action_type:
            # Fallback or error
            response_json = json.dumps({
                "status": "error",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "Could not parse action."}]}]
            })
        elif action_type == "finish":
            response_json = json.dumps({
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": [{"text": thought}]},
                    {"type": "message", "content": [{"type": "output_text", "text": f"DONE. {action_args.get('message', 'Task completed.')}"}]}
                ]
            })
        else:
            response_json = json.dumps({
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": [{"text": thought}]},
                    {"type": "computer_call", "action": {"type": action_type, **action_args}}
                ]
            })

        self.logger.debug(f"UITARS response: {response_text}")

        # Parse response into an Action using the UI-TARS action space.
        action = self.action_space.parse_response(response_json)

        self.logger.debug(f"UITARS agent returned action: {action.action_type}")
        if action.reasoning:
            self.logger.debug(f"Reasoning: {action.reasoning[:200]}...")

        return action

    def reset(self) -> None:
        """
        Reset agent state for a new task.

        Clears conversation history.
        """
        self.logger.debug("Resetting UITARS agent")
        self.history_screenshots = []
        self.history_responses = []
        self.instruction = None

    def set_instruction(self, instruction: str) -> None:
        """
        Set the task instruction for the agent.

        Args:
            instruction: Task description/instruction
        """
        self.instruction = instruction
        self.logger.debug(f"Set instruction: {instruction[:100]}...")

    def close(self) -> None:
        """
        Clean up agent resources.
        """
        self.logger.debug("Closed UITARS agent")
