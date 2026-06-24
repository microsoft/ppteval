"""Native OpenCUA agent for ppteval."""

import json
import logging
import time
from pathlib import Path
from typing import Any

import litellm
import yaml

from ppteval.action_spaces.opencua import OpenCUAActionSpace, parse_response_to_cot_and_action
from ppteval.action_spaces.opencua_prompts import (
    ACTION_HISTORY_TEMPLATE,
    INSTRUCTION_TEMPLATE,
    OBSERVATION_HISTORY_TEMPLATE,
    STEP_TEMPLATE,
    SYSTEM_PROMPT_V1_L1,
    SYSTEM_PROMPT_V1_L2,
    SYSTEM_PROMPT_V1_L3,
    THOUGHT_HISTORY_TEMPLATE,
    build_sys_prompt,
)
from ppteval.action_spaces.opencua_utils import process_image_for_opencua
from ppteval.config import OpenCUAConfig
from ppteval.core.base import Action, Agent, GUIState, State


class OpenCUAAgent(Agent):
    """OpenCUA model wrapper for the ppteval Agent interface."""

    def __init__(self, config: dict[str, Any] | OpenCUAConfig | str | Path | None = None):
        self.logger = logging.getLogger(__name__)

        if config is None:
            config_path = Path(__file__).parent.parent / "configs" / "opencua.yaml"
            self.agent_config = OpenCUAConfig.from_yaml(config_path) if config_path.exists() else OpenCUAConfig()
        elif isinstance(config, (str, Path)):
            self.agent_config = OpenCUAConfig.from_yaml(config)
        elif isinstance(config, dict):
            self.agent_config = OpenCUAConfig(**config)
        elif isinstance(config, OpenCUAConfig):
            self.agent_config = config
        else:
            raise ValueError(f"Config must be dict, OpenCUAConfig, Path, or None, got {type(config)}")

        self.action_space = OpenCUAActionSpace()
        self.instruction: str | None = None

        self.model = self.agent_config.model_name
        self.api_key = self.agent_config.api_key
        self.base_url = self.agent_config.base_url
        if not self.model:
            raise ValueError("model_name must be provided in the config for OpenCUA agent.")
        if not self.api_key:
            raise ValueError("api_key must be provided for the LLM endpoint.")

        self.display_size = {"width": self.agent_config.display_size.width, "height": self.agent_config.display_size.height}
        self.screen_size = (self.agent_config.display_size.width, self.agent_config.display_size.height)
        self.coordinate_type = self.agent_config.coordinate_type
        self.cot_level = self.agent_config.cot_level
        self.history_type = self.agent_config.history_type
        self.max_image_history_length = self.agent_config.max_image_history_length
        self.max_steps = self.agent_config.max_steps
        self.password = self.agent_config.password

        if self.agent_config.use_old_sys_prompt:
            if self.cot_level == "l1":
                self.system_prompt = SYSTEM_PROMPT_V1_L1
            elif self.cot_level == "l2":
                self.system_prompt = SYSTEM_PROMPT_V1_L2.format(password=self.password)
            elif self.cot_level == "l3":
                self.system_prompt = SYSTEM_PROMPT_V1_L3
            else:
                raise ValueError("Invalid cot_level. Choose from 'l1', 'l2', or 'l3'.")
        else:
            self.system_prompt = build_sys_prompt(
                level=self.cot_level,
                password=self.password,
                use_random=False,
            )

        if self.history_type == "action_history":
            self.history_template = ACTION_HISTORY_TEMPLATE
        elif self.history_type == "thought_history":
            self.history_template = THOUGHT_HISTORY_TEMPLATE
        elif self.history_type == "observation_history":
            self.history_template = OBSERVATION_HISTORY_TEMPLATE
        else:
            raise ValueError(f"Invalid history type: {self.history_type}")

        self.actions: list[str] = []
        self.observations: list[dict[str, Any]] = []
        self.cots: list[dict[str, Any]] = []
        self.screenshots: list[str] = []

        self.logger.info(f"Initialized OpenCUAAgent with model: {self.agent_config.model_name}")

    @staticmethod
    def _load_yaml_config(path: Path) -> OpenCUAConfig:
        """Load OpenCUAConfig from YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return OpenCUAConfig(**data)

    def step(self, state: State) -> Action:
        """Take one OpenCUA step."""
        if not isinstance(state, GUIState):
            raise ValueError(f"OpenCUAAgent requires GUIState, got {type(state)}")
        if self.instruction is None:
            raise ValueError("Instruction not set. Call set_instruction() first.")

        response_json = self._step_with_screenshot(self.action_space.format_state(state), self.instruction)
        action = self.action_space.parse_response(response_json)
        self.logger.debug(f"OpenCUA agent returned action: {action.action_type}")
        return action

    def _build_messages(self, screenshot: bytes, instruction: str) -> list[dict[str, Any]]:
        """Build OpenCUA messages with recent image history and older text history."""
        processed_image, _, _, _, _ = process_image_for_opencua(screenshot)
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        instruction_prompt = INSTRUCTION_TEMPLATE.format(instruction=instruction)

        history_step_texts = []
        for i in range(len(self.actions)):
            history_content = STEP_TEMPLATE.format(step_num=i + 1) + self.history_template.format(
                observation=self.cots[i].get("observation", ""),
                thought=self.cots[i].get("thought", ""),
                action=self.cots[i].get("action", ""),
            )

            if i > len(self.actions) - self.max_image_history_length:
                if i < len(self.screenshots):
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{self.screenshots[i]}"},
                                }
                            ],
                        }
                    )
                messages.append({"role": "assistant", "content": history_content})
            else:
                history_step_texts.append(history_content)
                if i == len(self.actions) - self.max_image_history_length:
                    messages.append({"role": "assistant", "content": "\n".join(history_step_texts)})

        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{processed_image}"},
                    },
                    {"type": "text", "text": instruction_prompt},
                ],
            }
        )

        return messages

    def _step_with_screenshot(self, screenshot: bytes, instruction: str) -> str:
        """Run one native OpenCUA model step and return the response JSON."""
        current_step = len(self.actions)
        self.logger.info(f"OpenCUA step {current_step + 1}: {instruction}")

        processed_image, _, _, _, _ = process_image_for_opencua(screenshot)
        messages = self._build_messages(screenshot, instruction)

        max_retry = 5
        low_level_instruction = None
        pyautogui_actions = None
        other_cot: dict[str, Any] = {}

        for retry_count in range(max_retry):
            try:
                completion_kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.agent_config.max_tokens,
                    "top_p": self.agent_config.top_p,
                    "temperature": self.agent_config.temperature if retry_count == 0 else max(0.2, self.agent_config.temperature),
                    "api_key": self.api_key,
                }
                if self.base_url:
                    completion_kwargs["base_url"] = self.base_url

                response = litellm.completion(**completion_kwargs)
                response_text = response.choices[0].message.content or ""
                if not response_text:
                    raise ValueError(f"No response found in the response:\n{response}.")

                low_level_instruction, pyautogui_actions, other_cot = parse_response_to_cot_and_action(response_text, self.screen_size, self.coordinate_type)
                if "<Error>" in low_level_instruction or not pyautogui_actions:
                    raise ValueError(f"Error parsing response: {low_level_instruction}")
                break

            except Exception as e:
                self.logger.warning(f"OpenCUA step attempt {retry_count + 1}/{max_retry} failed: {e}")
                if retry_count == max_retry - 1:
                    return json.dumps(
                        {
                            "status": "error",
                            "output": [
                                {"type": "reasoning", "summary": [{"text": str(e)}]},
                                {"type": "message", "content": [{"type": "output_text", "text": "FAIL. Maximum retries reached."}]},
                            ],
                        }
                    )
                time.sleep(1)

        self.screenshots.append(processed_image)
        self.observations.append({"screenshot": screenshot})
        self.actions.append(low_level_instruction or "")
        self.cots.append(other_cot)

        if len(self.actions) >= self.max_steps and pyautogui_actions and "computer.terminate" not in pyautogui_actions[0].lower():
            low_level_instruction = "Fail the task because reaching the maximum step limit."
            pyautogui_actions = ["FAIL"]
            other_cot["code"] = "FAIL"

        if not pyautogui_actions:
            action_output = {
                "status": "error",
                "output": [
                    {"type": "reasoning", "summary": [{"text": str(other_cot)}]},
                    {"type": "message", "content": [{"type": "output_text", "text": "Could not parse action from response."}]},
                ],
            }
        else:
            action_code = pyautogui_actions[0]
            if action_code == "DONE":
                action_output = {
                    "status": "completed",
                    "output": [
                        {"type": "reasoning", "summary": [{"text": other_cot.get("thought", "")}]},
                        {"type": "message", "content": [{"type": "output_text", "text": "DONE. Task completed successfully."}]},
                    ],
                }
            elif action_code == "FAIL":
                action_output = {
                    "status": "completed",
                    "output": [
                        {"type": "reasoning", "summary": [{"text": other_cot.get("thought", "")}]},
                        {"type": "message", "content": [{"type": "output_text", "text": "DONE. Task failed."}]},
                    ],
                }
            elif action_code == "WAIT":
                action_output = {
                    "status": "completed",
                    "output": [
                        {"type": "reasoning", "summary": [{"text": other_cot.get("thought", "")}]},
                        {"type": "computer_call", "action": {"type": "wait", "duration": 20}},
                    ],
                }
            else:
                action_output = {
                    "status": "completed",
                    "output": [
                        {"type": "reasoning", "summary": [{"text": other_cot.get("thought", "")}]},
                        {"type": "computer_call", "action": {"type": "pyautogui", "code": action_code}},
                    ],
                }

        return json.dumps(action_output)

    def reset(self) -> None:
        """Reset agent state for a new task."""
        self.instruction = None
        self.actions = []
        self.observations = []
        self.cots = []
        self.screenshots = []

    def set_instruction(self, instruction: str) -> None:
        """Set the task instruction."""
        self.instruction = instruction

    def close(self) -> None:
        """No persistent resources to clean up."""
        pass
