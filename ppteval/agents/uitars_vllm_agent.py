"""
UI-TARS agent variant that talks to an OpenAI-compatible Chat Completions
endpoint (e.g. vLLM ``vllm serve``) instead of the bespoke multipart
endpoint used by the original :class:`UITARSAgent`.

This is what we use to evaluate the open-weights UI-TARS 1.5 7B model
once it is hosted on an Azure ML compute instance behind a vLLM server +
devtunnel/SSH-forward.

Design choices
--------------
* Inherits from :class:`UITARSAgent` to reuse:
  - The UI-TARS prompt template (``UI_TARS_INSTRUCTION``).
  - The action parser (``_parse_action``).
  - The history scaffolding (``history_screenshots``, ``history_responses``).
  - ``reset()`` / ``set_instruction()`` / ``close()``.
* Overrides ``__init__`` to read :class:`UITARSVLLMConfig` and prepare a
  litellm client.
* Overrides ``step()`` to issue an OpenAI ``/v1/chat/completions`` request
  with the current screenshot + a rolling history of past screenshots and
  raw model responses, in the layout suggested by the UI-TARS reference
  implementation in OSWorld.

The model is expected to return a plain-text response of the form::

    Thought: ...
    Action: click(start_box='<|box_start|>(x,y)<|box_end|>')

which we then parse and lift into the same JSON envelope the
``UITARSActionSpace`` expects (kept identical to ``UITARSAgent.step``).
"""

from __future__ import annotations

import base64
import json
import logging
import math
import random
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import litellm
import yaml
from PIL import Image

from ppteval.action_spaces import UITARSActionSpace
from ppteval.agents.uitars_agent import UI_TARS_INSTRUCTION, UITARSAgent
from ppteval.config import UITARSVLLMConfig
from ppteval.core.base import Action, GUIState, State
from ppteval.utils.llm_telemetry import LLMUsageTelemetry

# ---------------------------------------------------------------------------
# UI-TARS / qwen2.5-vl image + coordinate helpers (ported from OSWorld).
# UI-TARS 1.5 emits absolute pixel coordinates in the *smart-resized* image
# grid. We must resize the screenshot to those dims before sending and rescale
# the model's coords back to the real screen grid for action execution.
# ---------------------------------------------------------------------------
_IMAGE_FACTOR = 28
_MIN_PIXELS = 100 * _IMAGE_FACTOR * _IMAGE_FACTOR
_MAX_PIXELS = 16384 * _IMAGE_FACTOR * _IMAGE_FACTOR
_MAX_RATIO = 200


def _round_by_factor(n: float, f: int) -> int:
    return int(round(n / f) * f)


def _ceil_by_factor(n: float, f: int) -> int:
    return int(math.ceil(n / f) * f)


def _floor_by_factor(n: float, f: int) -> int:
    return int(math.floor(n / f) * f)


def _smart_resize(
    height: int,
    width: int,
    factor: int = _IMAGE_FACTOR,
    min_pixels: int = _MIN_PIXELS,
    max_pixels: int = _MAX_PIXELS,
) -> tuple[int, int]:
    """Return (h, w) divisible by ``factor`` with aspect-ratio preserved
    and pixel count clamped to ``[min_pixels, max_pixels]``."""
    if max(height, width) / min(height, width) > _MAX_RATIO:
        raise ValueError(
            f"absolute aspect ratio must be <= {_MAX_RATIO}, got {max(height, width) / min(height, width)}"
        )
    h_bar = max(factor, _round_by_factor(height, factor))
    w_bar = max(factor, _round_by_factor(width, factor))
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = max(factor, _floor_by_factor(height / beta, factor))
        w_bar = max(factor, _floor_by_factor(width / beta, factor))
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = _ceil_by_factor(height * beta, factor)
        w_bar = _ceil_by_factor(width * beta, factor)
    return h_bar, w_bar


# Matches start_box/end_box='(x,y)' with optional <|box_start|>/<|box_end|>.
_COORD_PAT = re.compile(
    r"(start_box|end_box)='"
    r"(?:<\|box_start\|>)?\((\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\)(?:<\|box_end\|>)?"
    r"'"
)


def _rescale_coords_in_text(
    text: str, sr_w: int, sr_h: int, orig_w: int, orig_h: int
) -> str:
    """Rewrite model output coords from the smart-resized grid to screen px."""
    if sr_w == orig_w and sr_h == orig_h:
        return text

    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        x = float(m.group(2))
        y = float(m.group(3))
        nx = int(round(x / sr_w * orig_w))
        ny = int(round(y / sr_h * orig_h))
        return f"{key}='({nx},{ny})'"

    return _COORD_PAT.sub(_sub, text)


def _add_box_token(text: str) -> str:
    """Wrap bare coords in past assistant responses with the box tokens
    UI-TARS was trained to emit, mirroring OSWorld's ``add_box_token``."""

    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        x = m.group(2)
        y = m.group(3)
        return f"{key}='<|box_start|>({x},{y})<|box_end|>'"

    return _COORD_PAT.sub(_sub, text)


class UITARSVLLMAgent(UITARSAgent):
    """UI-TARS agent backed by an OpenAI-compatible chat-completions API."""

    # We deliberately do NOT call ``UITARSAgent.__init__`` because it tries
    # to read ``endpoint_url``/``token`` off the legacy ``UITARSConfig``;
    # we replicate the parts of the parent constructor we still need.
    def __init__(self, config: dict[str, Any] | UITARSVLLMConfig | str | Path | None = None):
        self.logger = logging.getLogger(__name__)

        if config is None:
            default = Path(__file__).parent.parent / "configs" / "uitars1.5-7B-vllm.yaml"
            self.agent_config = self._load_yaml_config(default)
        elif isinstance(config, (str, Path)):
            self.agent_config = self._load_yaml_config(Path(config))
        elif isinstance(config, dict):
            self.agent_config = UITARSVLLMConfig(**config)
        elif isinstance(config, UITARSVLLMConfig):
            self.agent_config = config
        else:
            raise ValueError(
                f"Config must be dict, UITARSVLLMConfig, Path, or None, got {type(config)}"
            )

        self.action_space = UITARSActionSpace()
        self.instruction: str | None = None
        self.history_screenshots: list[str] = []  # base64 strings
        self.history_responses: list[str] = []

        self.model_name = self.agent_config.model_name
        self.base_url = self.agent_config.base_url
        self.api_key = self.agent_config.api_key
        self.temperature = self.agent_config.temperature
        self.top_p = self.agent_config.top_p
        self.max_tokens = self.agent_config.max_tokens
        self.max_retries = self.agent_config.max_retries
        self.timeout_seconds = self.agent_config.timeout_seconds
        self.max_image_history_length = self.agent_config.max_image_history_length
        self.last_telemetry = LLMUsageTelemetry()

        self.logger.info(
            "Initialized UITARSVLLMAgent(model=%s, base_url=%s)",
            self.model_name,
            self.base_url,
        )

    @staticmethod
    def _load_yaml_config(path: Path) -> UITARSVLLMConfig:
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return UITARSVLLMConfig.from_yaml(path) if path.exists() else UITARSVLLMConfig(**data)

    # ------------------------------------------------------------------
    # Message construction
    # ------------------------------------------------------------------
    def _build_messages(self, current_screenshot_b64: str) -> list[dict[str, Any]]:
        """Build an OpenAI chat-completions ``messages`` list.

        Layout follows the UI-TARS OSWorld reference: a single user turn
        carries the prompt text and the current screenshot, optionally
        preceded by a rolling history of (past screenshot, past assistant
        response) pairs.
        """
        assert self.instruction is not None
        prompt = UI_TARS_INSTRUCTION.substitute(instruction=self.instruction)

        # Keep only the most recent ``max_image_history_length`` past steps.
        if self.max_image_history_length > 0:
            history = list(zip(
                self.history_screenshots[-self.max_image_history_length:],
                self.history_responses[-self.max_image_history_length:],
            ))
        else:
            history = []

        messages: list[dict[str, Any]] = []

        # System / instruction is delivered in the first user turn so we
        # stay aligned with the reference UI-TARS prompt format.
        first_user_content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
        ]
        messages.append({"role": "user", "content": first_user_content})

        # Replay history: each past screenshot + the model's prior response.
        # Past responses are wrapped with <|box_start|>/<|box_end|> tokens so
        # the model sees the format it was trained to emit in its own history.
        for past_img_b64, past_response in history:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{past_img_b64}"},
                        }
                    ],
                }
            )
            messages.append(
                {"role": "assistant", "content": _add_box_token(past_response)}
            )

        # Current screenshot as the latest user turn.
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{current_screenshot_b64}"},
                    }
                ],
            }
        )
        return messages

    def _call_llm(self, messages: list[dict[str, Any]]) -> str:
        """Call the OpenAI-compatible endpoint with retry/backoff."""
        base_delay = 1.0
        last_err: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model_name,
                    "messages": messages,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "timeout": self.timeout_seconds,
                }
                if self.api_key:
                    kwargs["api_key"] = self.api_key
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                # litellm needs an openai/ prefix to route to the chat
                # completions OpenAI-compat path when using a custom base_url.
                if not kwargs["model"].startswith("openai/"):
                    kwargs["model"] = f"openai/{kwargs['model']}"

                response = litellm.completion(**kwargs)
                self.last_telemetry.record_litellm_response(response, model=self.model_name)
                content = response.choices[0].message.content or ""
                return content
            except Exception as e:  # noqa: BLE001 — broad on purpose for retry
                last_err = e
                if attempt == self.max_retries:
                    break
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                self.logger.warning(
                    "UI-TARS vLLM call failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1,
                    self.max_retries + 1,
                    e,
                    delay,
                )
                time.sleep(delay)

        raise RuntimeError(
            f"UI-TARS vLLM call failed after {self.max_retries + 1} attempts: {last_err}"
        )

    # ------------------------------------------------------------------
    # Agent.step
    # ------------------------------------------------------------------
    def step(self, state: State) -> Action:
        if not isinstance(state, GUIState):
            raise ValueError(f"UITARSVLLM requires GUIState, got {type(state)}")
        if self.instruction is None:
            raise ValueError("Instruction not set. Call set_instruction() first.")

        screenshot_bytes = self.action_space.format_state(state)

        # Smart-resize the screenshot to a grid divisible by 28 (qwen2.5-vl
        # tiling) so the model's pixel-space coords map cleanly back to it.
        with Image.open(BytesIO(screenshot_bytes)) as _img:
            img = _img.convert("RGB")
        orig_w, orig_h = img.width, img.height
        sr_h, sr_w = _smart_resize(orig_h, orig_w)
        if (sr_w, sr_h) != (orig_w, orig_h):
            img_resized = img.resize((sr_w, sr_h), Image.LANCZOS)
        else:
            img_resized = img
        _buf = BytesIO()
        img_resized.save(_buf, format="PNG")
        screenshot_b64 = base64.b64encode(_buf.getvalue()).decode("utf-8")

        messages = self._build_messages(screenshot_b64)

        self.logger.debug(
            "UITARS vLLM request: model=%s history_steps=%d msg_turns=%d screen=%dx%d sr=%dx%d",
            self.model_name,
            min(len(self.history_screenshots), self.max_image_history_length),
            len(messages),
            orig_w,
            orig_h,
            sr_w,
            sr_h,
        )

        response_text = self._call_llm(messages).strip()

        # Persist this step into history for the next turn. We store the raw
        # response (in the smart-resized coord grid) alongside the resized
        # screenshot so coords and image are consistent on replay.
        self.history_screenshots.append(screenshot_b64)
        self.history_responses.append(response_text)

        # Rescale coords from the smart-resized grid back to actual screen
        # pixels before handing off to the parent's action parser.
        scaled_text = _rescale_coords_in_text(
            response_text, sr_w, sr_h, orig_w, orig_h
        )

        # Parse the response in the standard UI-TARS format. Mirrors the
        # legacy agent so downstream code is identical.
        thought_match = re.search(r"Thought:\s*(.+?)(?=\s*Action:\s|$)", scaled_text, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else ""
        action_match = re.search(r"Action:\s*(.+?)\s*$", scaled_text, re.DOTALL)
        action_str = action_match.group(1).strip() if action_match else ""

        action_type, action_args = self._parse_action(action_str) if action_str else (None, None)

        if not action_type:
            response_json = json.dumps(
                {
                    "status": "error",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": f"Could not parse action. Raw: {response_text[:300]}",
                                }
                            ],
                        }
                    ],
                }
            )
        elif action_type == "finish" or action_type == "finished":
            response_json = json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {"type": "reasoning", "summary": [{"text": thought}]},
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": f"DONE. {(action_args or {}).get('message', 'Task completed.')}",
                                }
                            ],
                        },
                    ],
                }
            )
        else:
            response_json = json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {"type": "reasoning", "summary": [{"text": thought}]},
                        {
                            "type": "computer_call",
                            "action": {"type": action_type, **(action_args or {})},
                        },
                    ],
                }
            )

        self.logger.debug("UITARS vLLM raw response: %s", response_text[:400])
        action = self.action_space.parse_response(response_json)
        self.logger.debug(
            "UITARS vLLM parsed action: %s args=%s",
            action.action_type,
            getattr(action, "params", None),
        )
        return action

    def reset(self) -> None:
        """Reset conversation history and task-scoped telemetry."""
        super().reset()
        self.last_telemetry = LLMUsageTelemetry()
