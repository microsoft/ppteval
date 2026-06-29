"""
OpenAI GPT-5.x Computer Use Agent (GA `computer` tool) for ppteval.

Compatible with both ``gpt-5.5`` and ``gpt-5.4`` via the GA `computer` tool.

Key differences from the legacy CUA (`computer-use-preview`) agent:
- Tool schema is just ``{"type": "computer"}`` — no display dims / environment.
- ``computer_call`` items carry a batched ``actions[]`` instead of a single
  ``action``. The API expects ONE screenshot response per batch (keyed by the
  last ``call_id``), so this agent queues actions and only fetches the next
  screenshot once the queue drains.
- Mouse actions may carry an optional ``keys[]`` (modifier keys to hold). We
  expand those into ``keydown``/action/``keyup`` triples so the sandbox can
  actually hold the modifier while the click/drag executes.
- No ``truncation`` parameter.
- Screenshot replies use ``computer_screenshot`` with ``detail="original"``.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from string import Template
from typing import Any

import yaml
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI, OpenAI

from ppteval.action_spaces import GPT5xActionSpace
from ppteval.config import GPT5xConfig
from ppteval.core.base import Action, Agent, GUIState, State
from ppteval.utils.llm_telemetry import LLMUsageTelemetry

GPT5X_INSTRUCTION = Template("""
Task: ${instruction}

You absolutely must avoid asking any clarification or follow-up questions--just execute the task as best you can with what you're given.
Refrain from asking any "Yes" or "No" questions about whether you should proceed--just assume the answer is always "Yes".
When you are done with the task (or have tried and found you cannot complete it), you must explicitly communicate so by prepending the phrase "DONE." to your message.
""")


class GPT5xAgent(Agent):
    """PPTEval agent for the GA ``computer`` tool (GPT-5.4 / GPT-5.5)."""

    def __init__(
        self,
        config: dict[str, Any] | GPT5xConfig | str | Path | None = None,
    ):
        self.logger = logging.getLogger(__name__)

        # Load configuration
        if config is None:
            config_path = Path(__file__).parent.parent / "configs" / "gpt5x.yaml"
            if config_path.exists():
                self.agent_config = self._load_yaml_config(config_path)
            else:
                self.agent_config = GPT5xConfig()
        elif isinstance(config, (str, Path)):
            self.agent_config = self._load_yaml_config(Path(config))
        elif isinstance(config, dict):
            self.agent_config = GPT5xConfig(**config)
        elif isinstance(config, GPT5xConfig):
            self.agent_config = config
        else:
            raise ValueError(
                f"Config must be dict, GPT5xConfig, Path, or None, got {type(config)}"
            )

        self.action_space = GPT5xActionSpace()
        self.instruction: str | None = None

        self.model = self.agent_config.model_name
        endpoint = self.agent_config.endpoint
        base_url = self.agent_config.base_url
        api_key = self.agent_config.api_key

        # Initialize OpenAI client (Azure uses managed identity by default).
        if endpoint == "azure":
            api_version = self.agent_config.api_version

            if not base_url:
                raise ValueError(
                    "GPT5xConfig.base_url is empty. Set GPT5X_BASE_URL to the "
                    "Azure endpoint host (e.g. https://<resource>.openai.azure.com) "
                    "without any /openai/... path or ?api-version=... query."
                )
            # The Azure OpenAI SDK appends /openai/... and the api-version query
            # itself. Reject path/query on the endpoint so we fail fast instead of
            # making a malformed request later.
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            if parsed.path not in ("", "/") or parsed.query:
                raise ValueError(
                    f"GPT5xConfig.base_url must be a bare host URL, got {base_url!r}. "
                    f"Use {parsed.scheme}://{parsed.netloc} instead and let the SDK "
                    "build the /openai/responses path and api-version query."
                )

            def token_provider() -> str:
                credential = DefaultAzureCredential()
                token = credential.get_token(
                    "https://cognitiveservices.azure.com/.default"
                ).token
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

        # Conversation/response state
        self.previous_response_id: str | None = None
        # call_id used to attach the next screenshot response.
        self.previous_computer_call_id: str | None = None
        self.last_telemetry = LLMUsageTelemetry()

        # Display configuration (kept for symmetry with CUAAgent / prompts).
        self.display_size: dict[str, int] = {
            "width": self.agent_config.display_size.width,
            "height": self.agent_config.display_size.height,
        }
        # GA `computer` tool: no display dims or environment fields needed.
        self.tools: list[dict[str, Any]] = [{"type": "computer"}]

        self.logger.info(f"Initialized GPT5xAgent with model: {self.model}")

    @staticmethod
    def _load_yaml_config(path: Path) -> GPT5xConfig:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return GPT5xConfig(**data)

    # ------------------------------------------------------------------ #
    # Agent interface
    # ------------------------------------------------------------------ #

    def step(self, state: State) -> Action:
        if not isinstance(state, GUIState):
            raise ValueError(f"GPT5xAgent requires GUIState, got {type(state)}")
        if self.instruction is None:
            raise ValueError("Instruction not set. Call set_instruction() first.")

        # One API call per step. The model may return a `computer_call` with a
        # batched `actions[]`; we parse them all into sub-Actions and wrap
        # them in a single composite Action so the orchestrator counts this
        # as exactly one step (one model decision).
        screenshot = self.action_space.format_state(state)
        screenshot_b64 = base64.b64encode(screenshot).decode("utf-8")

        if self.previous_response_id is None:
            # First turn: send the instruction.
            prompt = GPT5X_INSTRUCTION.substitute(instruction=self.instruction)
            response = self.client.responses.create(
                model=self.model,
                input=prompt,
                tools=self.tools,
                reasoning={"effort": self.agent_config.reasoning_effort},
            )
        else:
            # Subsequent turns: send ONE screenshot keyed to the previous
            # batch's terminating call_id.
            data = [
                {
                    "type": "computer_call_output",
                    "call_id": self.previous_computer_call_id,
                    "output": {
                        "type": "computer_screenshot",
                        "image_url": f"data:image/png;base64,{screenshot_b64}",
                        "detail": "original",
                    },
                }
            ]
            response = self.client.responses.create(
                model=self.model,
                previous_response_id=self.previous_response_id,
                input=data,
                tools=self.tools,
                reasoning={"effort": self.agent_config.reasoning_effort},
            )

        response_dict = response.dict()
        self.last_telemetry.record_openai_response(response_dict, model=self.model)
        self.previous_response_id = response_dict.get("id")

        # Find the (last) computer_call, record its call_id, collect actions[].
        actions_batch: list[dict[str, Any]] = []
        for item in response_dict.get("output", []):
            if item.get("type") == "computer_call":
                self.previous_computer_call_id = item.get("call_id") or item.get("id")
                batch = item.get("actions") or []
                if not batch and item.get("action"):
                    # Defensive: handle legacy single-action shape too.
                    batch = [item["action"]]
                actions_batch = batch

        if not actions_batch:
            # No computer_call in this response: fall back to the standard
            # CUA parsing path (handles finish/give_up/message-only).
            action = self.action_space.parse_response(json.dumps(response_dict))
            self.logger.debug(
                f"GPT5x agent returned terminal action: {action.action_type}"
            )
            return action

        # Expand modifier-key holds into keydown/action/keyup triples.
        flattened: list[dict[str, Any]] = []
        for raw in actions_batch:
            flattened.extend(GPT5xActionSpace.expand_modifier_keys(raw))

        # Parse each raw action into a sub-Action by synthesizing a minimal
        # single-action response_dict (preserves any reasoning/message items).
        passthrough_items = [
            item
            for item in response_dict.get("output", [])
            if item.get("type") != "computer_call"
        ]
        sub_actions: list[Action] = []
        for raw in flattened:
            synth = {
                "id": response_dict.get("id"),
                "reasoning_trace": response_dict.get("reasoning_trace"),
                "output": [
                    *passthrough_items,
                    {
                        "type": "computer_call",
                        "call_id": self.previous_computer_call_id,
                        "action": raw,
                    },
                ],
            }
            sub_actions.append(self.action_space.parse_response(json.dumps(synth)))

        composite_reasoning = sub_actions[0].reasoning if sub_actions else None
        self.logger.debug(
            f"GPT5x batch of {len(sub_actions)} action(s): "
            f"{[s.action_type for s in sub_actions]}"
        )
        return Action(
            action_type="batch",
            params={"size": len(sub_actions)},
            reasoning=composite_reasoning,
            sub_actions=sub_actions,
        )

    def reset(self) -> None:
        self.logger.debug("Resetting GPT5x agent")
        self.previous_response_id = None
        self.previous_computer_call_id = None
        self.instruction = None
        self.last_telemetry = LLMUsageTelemetry()

    def set_instruction(self, instruction: str) -> None:
        self.instruction = instruction
        self.logger.debug(f"Set instruction: {instruction[:100]}...")

    def close(self) -> None:
        self.logger.debug("Closed GPT5x agent")
