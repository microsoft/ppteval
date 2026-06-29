"""
Anthropic Claude Computer Use Agent for ppteval.

Self-contained Claude agent implementation with ppteval Agent interface.
Supports loading configuration from YAML files.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import litellm
import yaml

from ppteval.action_spaces import ClaudeActionSpace
from ppteval.config import ClaudeConfig
from ppteval.core.base import Action, Agent, GUIState, State
from ppteval.utils.llm_telemetry import LLMUsageTelemetry

CLAUDE_SYSTEM_PROMPT = """<SYSTEM_CAPABILITY>
You are utilising a web browser to interact with Microsoft Office Online applications.
You have access to PowerPoint, Word, Excel, and other Office apps through the browser.
</SYSTEM_CAPABILITY>

<IMPORTANT>
You absolutely must avoid asking any clarification or follow-up questions--just execute the task as best you can with what you're given.
Refrain from asking any "Yes" or "No" questions about whether you should proceed--just assume the answer is always "Yes".
When you are done with the task or are unable to complete it, use the finish tool to finish.
</IMPORTANT>"""


class ClaudeAgent(Agent):
    """
    PPTEval agent for Anthropic Claude Computer Use API.

    Integrates Claude with ppteval's Agent interface.
    Can load configuration from YAML file or accept dict/ClaudeConfig directly.
    """

    def __init__(self, config: dict[str, Any] | ClaudeConfig | str | Path | None = None):
        """
        Initialize Claude agent with configuration.

        Args:
            config: One of:
                - Path/str to YAML config file
                - Configuration dict
                - ClaudeConfig object
                - None (uses default config from ppteval/configs/claude.yaml)
        """
        self.logger = logging.getLogger(__name__)

        # Load configuration
        if config is None:
            # Load default config
            config_path = Path(__file__).parent.parent / "configs" / "claude.yaml"
            if config_path.exists():
                self.agent_config = self._load_yaml_config(config_path)
            else:
                self.agent_config = ClaudeConfig()
        elif isinstance(config, (str, Path)):
            # Load from YAML file
            self.agent_config = self._load_yaml_config(Path(config))
        elif isinstance(config, dict):
            self.agent_config = ClaudeConfig(**config)
        elif isinstance(config, ClaudeConfig):
            self.agent_config = config
        else:
            raise ValueError(f"Config must be dict, ClaudeConfig, Path, or None, got {type(config)}")

        self.action_space = ClaudeActionSpace()

        # Store instruction for multi-step interactions
        self.instruction: str | None = None

        # Extract configuration values
        self.model = self.agent_config.model_name
        self.base_url = self.agent_config.base_url
        self.api_key = self.agent_config.api_key

        if not self.model:
            raise ValueError("model_name must be provided in the config for Claude agent.")

        if not self.api_key:
            raise ValueError("api_key must be provided for Claude agent.")

        # Conversation state
        self.previous_response_id: Optional[str] = None
        self.last_telemetry = LLMUsageTelemetry()

        # Display configuration
        self.display_size: Dict[str, int] = {
            "width": self.agent_config.display_size.width,
            "height": self.agent_config.display_size.height
        }

        computer_tool_parameters = {
            "display_height_px": self.display_size["height"],
            "display_width_px": self.display_size["width"],
            "display_number": self.agent_config.display_number or 1,
        }
        enable_zoom = self.agent_config.computer_use_tool_type == "computer_20251124"
        if enable_zoom:
            computer_tool_parameters["enable_zoom"] = True

        computer_tool = {
            "type": self.agent_config.computer_use_tool_type,
            "function": {
                "name": "computer",
                "parameters": computer_tool_parameters,
            },
        }
        if enable_zoom:
            computer_tool["enable_zoom"] = True

        # Build tools list
        self.tools = [
            computer_tool,
            {
                "type": "function",
                "function": {
                    "name": "finish",
                    "description": "Finish the agent and return message to user.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "The message to the user with a reason for finishing.",
                            }
                        },
                    },
                },
            },
        ]

        self.messages = [
            {
                "role": "system",
                "content": CLAUDE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}
            }
        ]

        self.logger.info(f"Initialized Claude agent with model: {self.model}")
        self.logger.debug(f"Display size: {self.display_size}, Tools: {self.tools}")

    @staticmethod
    def _load_yaml_config(path: Path) -> ClaudeConfig:
        """Load ClaudeConfig from YAML file."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        return ClaudeConfig(**data)

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
            raise ValueError(f"Claude requires GUIState, got {type(state)}")

        if self.instruction is None:
            raise ValueError("Instruction not set. Call set_instruction() first.")

        # Format state for Claude agent (get screenshot bytes)
        screenshot = self.action_space.format_state(state)
        screenshot_b64 = base64.b64encode(screenshot).decode("utf-8")

        if self.previous_response_id is None:
            # First step: Add instruction and screenshot
            self.messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Instruction: {self.instruction}",
                            "cache_control": {"type": "ephemeral"}
                        }
                    ],
                }
            )
            self.messages[-1]["content"].append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{screenshot_b64}",
                    },
                    "cache_control": {"type": "ephemeral"},
                }
            )
        else:
            # Subsequent steps: Update screenshot
            self.messages[-1]["content"] = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{screenshot_b64}",
                    },
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        # Call Claude API via litellm
        # Build completion kwargs
        completion_kwargs = {
            "messages": self.messages,
            "model": self.model,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "tools": self.tools,
            "extra_headers": {"anthropic-beta": self.agent_config.computer_use_beta},
            "max_tokens": self.agent_config.max_tokens,
            "temperature": self.agent_config.temperature,
        }

        # Configure thinking / reasoning effort.
        injected_output_config = False
        reasoning_effort = self.agent_config.reasoning_effort
        if reasoning_effort == "adaptive":
            completion_kwargs["thinking"] = {"type": "adaptive"}
            injected_output_config = True
            # Adaptive thinking is incompatible with custom `temperature`.
            completion_kwargs.pop("temperature", None)
        else:
            completion_kwargs["reasoning_effort"] = reasoning_effort

        try:
            response = litellm.completion(**completion_kwargs)
            self.last_telemetry.record_litellm_response(response, model=self.model)
        finally:
            if injected_output_config:
                try:
                    del litellm.AnthropicConfig.output_config
                except AttributeError:
                    pass

        response_message = response.choices[0].message
        self.messages.append(response_message)

        tool_call = response_message.tool_calls[-1]
        self.previous_response_id = tool_call.id

        tool_result = {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
        }

        self.messages.append(tool_result)

        action_output_tool_type = "computer_call" if tool_result.get("name") == "computer" else "call"

        # Extract thinking/reasoning content
        thinking_text = ""
        if hasattr(response_message, "reasoning_content") and response_message.reasoning_content:
            # Standard reasoning content
            thinking_text = response_message.reasoning_content
        elif hasattr(response_message, "content") and response_message.content:
            # When thinking is enabled, check for thinking blocks in content
            if isinstance(response_message.content, list):
                for block in response_message.content:
                    if isinstance(block, dict) and block.get("type") == "thinking":
                        thinking_text = block.get("text", "")
                        break
                    elif hasattr(block, "type") and block.type == "thinking":
                        thinking_text = getattr(block, "text", "")
                        break

        action_output = {
            "status": "completed",
            "output": [
                {
                    "type": "reasoning",
                    "summary": [
                        {
                            "text": thinking_text,
                            "cache_control": {"type": "ephemeral"}
                        }
                    ],
                },
                {
                    "type": action_output_tool_type,
                    "action": {
                        "type": tool_result.get("name"),
                        **json.loads(tool_call.function.arguments),
                    },
                },
            ],
        }

        self.logger.debug(f"Claude response: {action_output}")

        # Parse response into an Action using the Claude action space.
        action = self.action_space.parse_response(json.dumps(action_output))

        self.logger.debug(f"Claude agent returned action: {action.action_type}")
        if action.reasoning:
            self.logger.debug(f"Reasoning: {action.reasoning[:200]}...")

        return action

    def reset(self) -> None:
        """
        Reset agent state for a new task.

        Clears conversation history.
        """
        self.logger.debug("Resetting Claude agent")
        self.messages = [
            {
                "role": "system",
                "content": CLAUDE_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}
            }
        ]
        self.previous_response_id = None
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
        self.logger.debug("Closed Claude agent")
