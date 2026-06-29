"""
OpenAI Computer Use Agent (CUA) for ppteval.

Self-contained CUA agent implementation with ppteval Agent interface.
"""

import base64
import json
import logging
from pathlib import Path
from string import Template
from typing import Any, Dict, Optional

import yaml
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI, OpenAI

from ppteval.action_spaces import CUAActionSpace
from ppteval.config import CUAConfig
from ppteval.core.base import Action, Agent, GUIState, State
from ppteval.utils.llm_telemetry import LLMUsageTelemetry

CUA_INSTRUCTION = Template("""
Task: ${instruction}

You absolutely must avoid asking any clarification or follow-up questions--just execute the task as best you can with what you're given.
Refrain from asking any "Yes" or "No" questions about whether you should proceed--just assume the answer is always "Yes".
When you are done with the task (or have tried and found you cannot complete it), you must explicitly communicate so by prepending the phrase "DONE." to your message.
""")


class CUAAgent(Agent):
    """
    PPTEval agent for OpenAI Computer Use Agent (CUA).

    Integrates Azure OpenAI/OpenAI with ppteval's Agent interface.
    Can load configuration from YAML file or accept dict/CUAConfig directly.
    """

    def __init__(self, config: dict[str, Any] | CUAConfig | str | Path | None = None):
        """
        Initialize CUA agent with configuration.

        Args:
            config: One of:
                - Path/str to YAML config file
                - Configuration dict
                - CUAConfig object
                - None (uses default config from ppteval/configs/cua.yaml)
        """
        self.logger = logging.getLogger(__name__)

        # Load configuration
        if config is None:
            # Load default config
            config_path = Path(__file__).parent.parent / "configs" / "cua.yaml"
            if config_path.exists():
                self.agent_config = self._load_yaml_config(config_path)
            else:
                self.agent_config = CUAConfig()
        elif isinstance(config, (str, Path)):
            # Load from YAML file
            self.agent_config = self._load_yaml_config(Path(config))
        elif isinstance(config, dict):
            self.agent_config = CUAConfig(**config)
        elif isinstance(config, CUAConfig):
            self.agent_config = config
        else:
            raise ValueError(f"Config must be dict, CUAConfig, Path, or None, got {type(config)}")
        self.action_space = CUAActionSpace()

        # Store instruction for multi-step interactions
        self.instruction: str | None = None

        # Extract configuration values
        self.model = self.agent_config.model_name
        base_url = self.agent_config.base_url
        endpoint = self.agent_config.endpoint
        api_key = self.agent_config.api_key

        # Initialize OpenAI client
        if endpoint == "azure":
            api_version = self.agent_config.api_version

            def token_provider() -> str:
                credential = DefaultAzureCredential()
                token = credential.get_token("https://cognitiveservices.azure.com/.default").token
                return token

            self.client = AzureOpenAI(
                azure_endpoint=base_url,
                azure_ad_token_provider=token_provider,
                api_version=api_version,
            )
        else:
            if not api_key:
                raise ValueError("api_key must be provided for the OpenAI endpoint.")
            self.client = OpenAI(api_key=api_key, base_url=base_url)

        # Conversation state
        self.previous_response_id: Optional[str] = None
        self.previous_computer_call_id: Optional[str] = None
        self.last_telemetry = LLMUsageTelemetry()

        # Display configuration
        self.display_size: Dict[str, int] = {
            "width": self.agent_config.display_size.width,
            "height": self.agent_config.display_size.height
        }
        self.tools = [
            {
                "type": "computer-preview",
                "display_width": self.display_size["width"],
                "display_height": self.display_size["height"],
                "environment": self.agent_config.environment,
            }
        ]

        self.logger.info(f"Initialized CUAAgent with model: {self.model}")
        self.logger.debug(f"Display size: {self.display_size}, Tools: {self.tools}")

    @staticmethod
    def _load_yaml_config(path: Path) -> CUAConfig:
        """Load CUAConfig from YAML file."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        return CUAConfig(**data)

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
            raise ValueError(f"CUAAgent requires GUIState, got {type(state)}")

        if self.instruction is None:
            raise ValueError("Instruction not set. Call set_instruction() first.")

        # Format state for CUA agent (get screenshot bytes)
        screenshot = self.action_space.format_state(state)

        # Call CUA model
        screenshot_b64 = base64.b64encode(screenshot).decode("utf-8")

        if self.previous_response_id is None:
            # First step: Start the conversation
            prompt = CUA_INSTRUCTION.substitute(instruction=self.instruction)
            response = self.client.responses.create(
                model=self.model,
                input=prompt,
                tools=self.tools,
                truncation=self.agent_config.truncation,
                temperature=self.agent_config.temperature,
                top_p=self.agent_config.top_p,
                reasoning={"effort": "medium"},  # Enable reasoning trace
            )
        else:
            # Subsequent steps: Continue the conversation
            data = [
                {
                    "type": "computer_call_output",
                    "call_id": self.previous_computer_call_id,
                    "output": {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{screenshot_b64}",
                    },
                }
            ]
            response = self.client.responses.create(
                model=self.model,
                previous_response_id=self.previous_response_id,
                input=data,
                tools=self.tools,
                truncation=self.agent_config.truncation,
                temperature=self.agent_config.temperature,
                top_p=self.agent_config.top_p,
                reasoning={"effort": "medium"},  # Enable reasoning trace
                extra_headers={},
            )

        response_dict = response.dict()
        self.last_telemetry.record_openai_response(response_dict, model=self.model)
        self.previous_response_id = response_dict.get("id")

        # Find the computer_call to get the next call_id
        for item in response_dict.get("output", []):
            if item.get("type") == "computer_call":
                self.previous_computer_call_id = item.get("call_id") or item.get("id")
                break

        self.logger.debug(f"CUA response: {response_dict}")

        # Parse response into an Action using the CUA action space.
        action = self.action_space.parse_response(json.dumps(response_dict))

        self.logger.debug(f"CUA agent returned action: {action.action_type}")
        if action.reasoning:
            self.logger.debug(f"Reasoning: {action.reasoning[:200]}...")

        return action

    def reset(self) -> None:
        """
        Reset agent state for a new task.

        Clears conversation history.
        """
        self.logger.debug("Resetting CUA agent")
        self.previous_response_id = None
        self.previous_computer_call_id = None
        self.instruction = None
        self.last_telemetry = LLMUsageTelemetry()

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
        self.logger.debug("Closed CUA agent")
