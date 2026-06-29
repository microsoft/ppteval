"""
Qwen3-VL Agent for ppteval.

Self-contained Qwen3-VL agent implementation with ppteval Agent interface.
Uses litellm as the unified API backend.

Based on the OSWorld Qwen3-VL implementation:
https://github.com/xlang-ai/OSWorld/blob/main/mm_agents/qwen3vl_agent.py
"""

import base64
import hashlib
import json
import logging
import math
import os
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Tuple

import litellm
import yaml
from PIL import Image

from ppteval.action_spaces.qwen3vl import Qwen3VLActionSpace
from ppteval.config import Qwen3VLConfig
from ppteval.core.base import Action, Agent, GUIState, State
from ppteval.utils.llm_telemetry import LLMUsageTelemetry


def round_by_factor(number: float, factor: int) -> int:
    """Round a number to the nearest multiple of factor."""
    return round(number / factor) * factor


def floor_by_factor(number: float, factor: int) -> int:
    """Floor a number to the nearest multiple of factor."""
    return int(number // factor) * factor


def ceil_by_factor(number: float, factor: int) -> int:
    """Ceil a number to the nearest multiple of factor."""
    return math.ceil(number / factor) * factor


def smart_resize(
    height: int,
    width: int,
    factor: int = 32,
    min_pixels: int = 56 * 56,
    max_pixels: int = 16 * 16 * 4 * 12800,
    max_long_side: int = 8192,
) -> Tuple[int, int]:
    """
    Smart resize for Qwen VL models (official implementation).

    Resizes dimensions to satisfy:
    1. Height and width are divisible by factor
    2. Total pixels are within [min_pixels, max_pixels]
    3. Longest side is within max_long_side
    4. Aspect ratio is preserved as much as possible
    """
    if height < 2 or width < 2:
        raise ValueError(f"height:{height} or width:{width} must be >= 2")
    if max(height, width) / min(height, width) > 200:
        raise ValueError(f"absolute aspect ratio must be smaller than 200, got {height} / {width}")

    # First, limit the longest side
    if max(height, width) > max_long_side:
        beta = max(height, width) / max_long_side
        height, width = int(height / beta), int(width / beta)

    # Round to nearest factor
    h_bar = round_by_factor(height, factor)
    w_bar = round_by_factor(width, factor)

    # Adjust if outside pixel bounds
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = floor_by_factor(height / beta, factor)
        w_bar = floor_by_factor(width / beta, factor)
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = ceil_by_factor(height * beta, factor)
        w_bar = ceil_by_factor(width * beta, factor)

    return h_bar, w_bar


def process_image(image_bytes: bytes) -> Tuple[str, int, int]:
    """
    Process an image for Qwen VL models.

    Returns:
        Tuple of (base64_encoded_image, processed_width, processed_height)
    """
    image = Image.open(BytesIO(image_bytes))
    width, height = image.size

    # Qwen3-VL defaults (patch_size=16, merge_size=2 -> factor=32; max_pixels sized for 1080p)
    resized_height, resized_width = smart_resize(
        height=height,
        width=width,
        factor=32,
        max_pixels=16 * 16 * 4 * 12800,
    )

    image = image.resize((resized_width, resized_height))

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    processed_bytes = buffer.getvalue()

    return base64.b64encode(processed_bytes).decode("utf-8"), resized_width, resized_height


def build_system_prompt(display_width: int, display_height: int, coordinate_type: str = "relative") -> str:
    """Build the system prompt with tools definition in OSWorld style."""

    if coordinate_type == "absolute":
        screen_info = f"The screen's resolution is {display_width}x{display_height}."
    else:
        screen_info = "The screen's resolution is 1000x1000."

    description_prompt = f"""Use a mouse and keyboard to interact with a computer, and take screenshots.
* This is an interface to a desktop GUI. You do not have access to a terminal or applications menu. You must click on desktop icons to start applications.
* Some applications may take time to start or process actions, so you may need to wait and take successive screenshots to see the results of your actions.
E.g. if you click on Firefox and a window doesn't open, try wait and taking another screenshot.
* {screen_info}
* Whenever you intend to move the cursor to click on an element like an icon,
you should consult a screenshot to determine the coordinates of the element before moving the cursor.
* If you tried clicking on a program or link but it failed to load even after waiting,
try adjusting your cursor position so that the tip of the cursor visually falls on the element that you want to click.
* Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. Don't click boxes on their edges unless asked."""

    action_description = """
* `key`: Performs key down presses on the arguments passed in order, then performs key releases in reverse order.
* `type`: Type a string of text on the keyboard.
* `mouse_move`: Move the cursor to a specified (x, y) pixel coordinate on the screen.
* `left_click`: Click the left mouse button at a specified (x, y) pixel coordinate on the screen.
* `left_click_drag`: Click and drag the cursor to a specified (x, y) pixel coordinate on the screen.
* `right_click`: Click the right mouse button at a specified (x, y) pixel coordinate on the screen.
* `middle_click`: Click the middle mouse button at a specified (x, y) pixel coordinate on the screen.
* `double_click`: Double-click the left mouse button at a specified (x, y) pixel coordinate on the screen.
* `triple_click`: Triple-click the left mouse button at a specified (x, y) pixel coordinate on the screen.
* `scroll`: Performs a scroll of the mouse scroll wheel.
* `hscroll`:  Performs a horizontal scroll (mapped to regular scroll).
* `wait`: Wait specified seconds for the change to happen.
* `terminate`: Terminate the current task and report its completion status."""

    tools_def = {
        "type": "function",
        "function": {
            "name_for_human": "computer_use",
            "name": "computer_use",
            "description": description_prompt,
            "parameters": {
                "properties": {
                    "action": {
                        "description": action_description,
                        "enum": ["key", "type", "mouse_move", "left_click", "left_click_drag", "right_click", "middle_click", "double_click", "triple_click", "scroll", "hscroll", "wait", "terminate"],
                        "type": "string",
                    },
                    "keys": {"description": "Required only by `action=key`.", "type": "array"},
                    "text": {"description": "Required only by `action=type`.", "type": "string"},
                    "coordinate": {"description": "The x,y coordinates for mouse actions.", "type": "array"},
                    "pixels": {"description": "The amount of scrolling.", "type": "number"},
                    "time": {"description": "The seconds to wait.", "type": "number"},
                    "status": {"description": "The status of the task.", "type": "string", "enum": ["success", "failure"]},
                },
                "required": ["action"],
                "type": "object",
            },
            "args_format": "Format the arguments as a JSON object.",
        },
    }

    system_prompt = f"""You are utilising an Ubuntu virtual machine with internet access. You are able to use the computer to solve Microsoft Office tasks.

You should avoid asking any clarification or follow-up questions--just execute the task as best you can with what you're given.
Refrain from asking any "Yes" or "No" questions about whether you should proceed--just assume the answer is always "Yes".
When you are done with the task or are unable to complete it, use action=terminate in the computer_use tool.

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{json.dumps(tools_def)}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{{"name": <function-name>, "arguments": <args-json-object>}}
</tool_call>

# Response format

Response format for every step:
1) Action: a short imperative describing what to do in the UI.
2) A single <tool_call>...</tool_call> block containing only the JSON: {{"name": <function-name>, "arguments": <args-json-object>}}.

Rules:
- Output exactly in the order: Action, <tool_call>.
- Be brief: one sentence for Action.
- Do not output anything else outside those parts.
- If finishing, use action=terminate in the tool call."""

    return system_prompt


class Qwen3VLAgent(Agent):
    """
    PPTEval agent for Qwen3-VL model.

    Integrates Qwen3-VL with ppteval's Agent interface using litellm.
    Based on the OSWorld implementation with the original action space.
    """

    def __init__(self, config: dict[str, Any] | Qwen3VLConfig | str | Path | None = None):
        """
        Initialize Qwen3-VL agent with configuration.

        Args:
            config: One of:
                - Path/str to YAML config file
                - Configuration dict
                - Qwen3VLConfig object
                - None (uses default config from ppteval/configs/qwen3vl.yaml)
        """
        self.logger = logging.getLogger(__name__)

        # Load configuration
        if config is None:
            # Load default config
            config_path = Path(__file__).parent.parent / "configs" / "qwen3vl.yaml"
            if config_path.exists():
                self.agent_config = self._load_yaml_config(config_path)
            else:
                self.agent_config = Qwen3VLConfig()
        elif isinstance(config, (str, Path)):
            # Load from YAML file
            self.agent_config = self._load_yaml_config(Path(config))
        elif isinstance(config, dict):
            self.agent_config = Qwen3VLConfig(**config)
        elif isinstance(config, Qwen3VLConfig):
            self.agent_config = config
        else:
            raise ValueError(f"Config must be dict, Qwen3VLConfig, Path, or None, got {type(config)}")

        self.action_space = Qwen3VLActionSpace()

        # Store instruction for multi-step interactions
        self.instruction: str | None = None

        # Extract configuration values
        self.model = self.agent_config.model_name
        self.api_key = self.agent_config.api_key
        self.base_url = self.agent_config.base_url
        self.max_tokens = self.agent_config.max_tokens
        self.temperature = self.agent_config.temperature
        self.top_p = self.agent_config.top_p
        self.top_k = self.agent_config.top_k
        self.history_n = self.agent_config.history_n
        self.coordinate_type = self.agent_config.coordinate_type

        # Display configuration
        self.display_size: Dict[str, int] = {"width": self.agent_config.display_size.width, "height": self.agent_config.display_size.height}

        # Build system prompt (OSWorld style)
        self.system_prompt = build_system_prompt(self.display_size["width"], self.display_size["height"], self.coordinate_type)

        # Conversation messages
        self.messages: List[dict] = [{"role": "system", "content": [{"type": "text", "text": self.system_prompt}]}]

        # History tracking
        self.screenshots: List[str] = []  # base64 encoded
        self.responses: List[str] = []
        self.actions: List[str] = []
        self.last_telemetry = LLMUsageTelemetry()
        self.action_records: List[dict[str, Any]] = []

        self.logger.info(f"Initialized Qwen3-VL agent with model: {self.model}")

    @staticmethod
    def _load_yaml_config(path: Path) -> Qwen3VLConfig:
        """Load Qwen3VLConfig from YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)

        return Qwen3VLConfig(**data)

    def _adjust_coordinates(self, x: float, y: float, original_width: int, original_height: int, processed_width: int, processed_height: int) -> Tuple[int, int]:
        """Adjust coordinates from processed to original resolution."""
        if self.coordinate_type == "absolute":
            if processed_width and processed_height:
                x_scale = original_width / processed_width
                y_scale = original_height / processed_height
                return int(x * x_scale), int(y * y_scale)
            return int(x), int(y)
        # Relative: scale from 0..999 grid
        print(f"Original width: {original_width}, Original height: {original_height}")
        x_scale = original_width / 999
        y_scale = original_height / 999
        return int(x * x_scale), int(y * y_scale)

    def _extract_action_args(
        self,
        args: Dict[str, Any],
        original_width: int,
        original_height: int,
        processed_width: int,
        processed_height: int,
        *,
        adjust_coordinates: bool,
    ) -> Dict[str, Any]:
        """Extract tool arguments, optionally projecting model coordinates to screen pixels."""
        action_args: Dict[str, Any] = {}

        if "coordinate" in args and args["coordinate"]:
            x, y = args["coordinate"]
            if adjust_coordinates:
                x, y = self._adjust_coordinates(x, y, original_width, original_height, processed_width, processed_height)
            action_args["coordinate"] = [x, y]

        for key in ["keys", "text", "pixels", "time", "status", "duration"]:
            if key in args:
                action_args[key] = args[key]

        return action_args

    def _parse_response(
        self,
        response_text: str,
        original_width: int,
        original_height: int,
        processed_width: int,
        processed_height: int,
    ) -> Tuple[str, str, Dict[str, Any], Dict[str, Any]]:
        """
        Parse LLM response in OSWorld format and extract action details.

        Returns:
            Tuple of (thought, action_type, execution_args, raw_model_args)
        """
        thought = ""
        action_type = ""
        action_args: Dict[str, Any] = {}
        raw_action_args: Dict[str, Any] = {}

        if not response_text or not response_text.strip():
            return thought, action_type, action_args, raw_action_args

        # Parse response lines
        lines = response_text.split("\n")
        inside_tool_call = False
        current_tool_call: List[str] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Extract thought/action description
            if line.lower().startswith("action:"):
                thought = line.split("Action:")[-1].strip()
                continue

            # Handle tool call tags
            if line.startswith("<tool_call>"):
                inside_tool_call = True
                continue
            elif line.startswith("</tool_call>"):
                if current_tool_call:
                    try:
                        tool_json = "\n".join(current_tool_call)
                        tool_call = json.loads(tool_json)
                        if tool_call.get("name") == "computer_use":
                            args = tool_call.get("arguments", {})
                            action_type = args.get("action", "")
                            action_args = self._extract_action_args(args, original_width, original_height, processed_width, processed_height, adjust_coordinates=True)
                            raw_action_args = self._extract_action_args(args, original_width, original_height, processed_width, processed_height, adjust_coordinates=False)
                    except (json.JSONDecodeError, KeyError) as e:
                        self.logger.error(f"Failed to parse tool call: {e}")
                    current_tool_call = []
                inside_tool_call = False
                continue

            if inside_tool_call:
                current_tool_call.append(line)
                continue

            # Try to parse standalone JSON (fallback)
            if line.startswith("{") and line.endswith("}"):
                try:
                    json_obj = json.loads(line)
                    if "name" in json_obj and "arguments" in json_obj:
                        args = json_obj.get("arguments", {})
                        action_type = args.get("action", "")
                        action_args = self._extract_action_args(args, original_width, original_height, processed_width, processed_height, adjust_coordinates=True)
                        raw_action_args = self._extract_action_args(args, original_width, original_height, processed_width, processed_height, adjust_coordinates=False)
                except json.JSONDecodeError:
                    pass

        # Process remaining tool call if any
        if current_tool_call:
            try:
                tool_json = "\n".join(current_tool_call)
                tool_call = json.loads(tool_json)
                if tool_call.get("name") == "computer_use":
                    args = tool_call.get("arguments", {})
                    action_type = args.get("action", "")
                    action_args = self._extract_action_args(args, original_width, original_height, processed_width, processed_height, adjust_coordinates=True)
                    raw_action_args = self._extract_action_args(args, original_width, original_height, processed_width, processed_height, adjust_coordinates=False)
            except (json.JSONDecodeError, KeyError) as e:
                self.logger.error(f"Failed to parse remaining tool call: {e}")

        return thought, action_type, action_args, raw_action_args

    def _build_instruction_prompt(self) -> str:
        """Build the instruction prompt with previous actions.

        Shows actions older than the visual/assistant history window. Recent
        actions are already present as assistant messages.
        """
        current_step = len(self.actions)
        history_start_idx = max(0, current_step - self.history_n)

        # Keep model-facing history in the model's coordinate system. Execution
        # coordinates are stored separately after parsing.
        previous_actions = []
        for i in range(history_start_idx):
            if i < len(self.action_records):
                record = self.action_records[i]
                params = record.get("raw_params") or {}
                thought = record.get("thought") or ""
                params_str = f" params={json.dumps(params, ensure_ascii=False)}" if params else ""
                thought_str = f" - {thought}" if thought else ""
                previous_actions.append(f"Step {i+1}: {record.get('action_type', '')}{params_str}{thought_str}")
            else:
                previous_actions.append(f"Step {i+1}: {self.actions[i]}")
        previous_actions_str = "\n".join(previous_actions) if previous_actions else "None"

        return f"""Please generate the next move according to the UI screenshot, instruction and previous actions.

Instruction: {self.instruction}

Previous actions:
{previous_actions_str}"""

    def _dump_llm_request(
        self,
        completion_kwargs: dict[str, Any],
        current_step: int,
        raw_screenshot: bytes,
        original_size: tuple[int, int],
        processed_size: tuple[int, int],
    ) -> None:
        """Optionally write a readable, secret-free snapshot of the Qwen LLM call."""
        dump_dir = os.getenv("QWEN3VL_DUMP_REQUEST_DIR")
        if not dump_dir:
            return

        path = Path(dump_dir)
        path.mkdir(parents=True, exist_ok=True)
        step_num = current_step + 1
        image_files: list[dict[str, Any]] = []

        raw_image_path = path / f"qwen3vl_request_step_{step_num:03d}_current_raw.png"
        raw_image_path.write_bytes(raw_screenshot)
        image_files.append(
            {
                "kind": "current_raw_screenshot",
                "path": str(raw_image_path),
                "width": original_size[0],
                "height": original_size[1],
                "sha256": hashlib.sha256(raw_screenshot).hexdigest(),
            }
        )

        def summarize_content_item(item: dict[str, Any], message_idx: int, content_idx: int) -> dict[str, Any]:
            if item.get("type") != "image_url":
                return item
            url = (item.get("image_url") or {}).get("url", "")
            prefix = "data:image/png;base64,"
            if url.startswith(prefix):
                image_b64 = url[len(prefix) :]
                image_bytes = base64.b64decode(image_b64)
                image_path = path / f"qwen3vl_request_step_{step_num:03d}_message_{message_idx:02d}_image_{content_idx:02d}.png"
                image_path.write_bytes(image_bytes)
                with Image.open(BytesIO(image_bytes)) as image:
                    width, height = image.size
                image_files.append(
                    {
                        "kind": "message_image",
                        "message_idx": message_idx,
                        "content_idx": content_idx,
                        "path": str(image_path),
                        "width": width,
                        "height": height,
                        "sha256": hashlib.sha256(image_bytes).hexdigest(),
                    }
                )
                return {
                    "type": "image_url",
                    "image_url": {
                        "url": f"{prefix}<omitted>",
                        "base64_length": len(image_b64),
                        "base64_sha256": hashlib.sha256(image_b64.encode("utf-8")).hexdigest(),
                        "bytes_sha256": hashlib.sha256(image_bytes).hexdigest(),
                        "dump_path": str(image_path),
                        "width": width,
                        "height": height,
                    },
                }
            return {"type": "image_url", "image_url": {"url": "<non-data-url-omitted>"}}

        def summarize_message(message: dict[str, Any], message_idx: int) -> dict[str, Any]:
            content = message.get("content")
            if isinstance(content, list):
                content = [summarize_content_item(item, message_idx, content_idx) if isinstance(item, dict) else item for content_idx, item in enumerate(content)]
            return {"role": message.get("role"), "content": content}

        sanitized = {
            "step": step_num,
            "model": completion_kwargs.get("model"),
            "temperature": completion_kwargs.get("temperature"),
            "top_p": completion_kwargs.get("top_p"),
            "top_k": (completion_kwargs.get("extra_body") or {}).get("top_k"),
            "max_tokens": completion_kwargs.get("max_tokens"),
            "original_size": {"width": original_size[0], "height": original_size[1]},
            "processed_size": {"width": processed_size[0], "height": processed_size[1]},
            "message_count": len(completion_kwargs.get("messages", [])),
            "messages": [summarize_message(message, message_idx) for message_idx, message in enumerate(completion_kwargs.get("messages", []))],
            "image_files": image_files,
        }

        (path / f"qwen3vl_request_step_{step_num:03d}.json").write_text(json.dumps(sanitized, indent=2), encoding="utf-8")

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
            raise ValueError(f"Qwen3VL requires GUIState, got {type(state)}")

        if self.instruction is None:
            raise ValueError("Instruction not set. Call set_instruction() first.")

        # Format state for agent (get screenshot bytes)
        screenshot = self.action_space.format_state(state)

        # Get original dimensions
        image = Image.open(BytesIO(screenshot))
        original_width, original_height = image.size

        # Process image for Qwen VL
        processed_image, processed_width, processed_height = process_image(screenshot)

        self.logger.debug(f"Original: {original_width}x{original_height}, Processed: {processed_width}x{processed_height}")

        # Store screenshot in history
        self.screenshots.append(processed_image)

        # Build instruction prompt
        instruction_prompt = self._build_instruction_prompt()

        # Build messages with history
        current_step = len(self.responses)
        history_len = min(self.history_n, current_step)

        # Rebuild messages from scratch for multi-turn
        self.system_prompt = build_system_prompt(processed_width, processed_height, self.coordinate_type)
        self.messages = [{"role": "system", "content": [{"type": "text", "text": self.system_prompt}]}]

        if history_len > 0:
            history_responses = self.responses[-history_len:]
            history_screenshots = self.screenshots[-history_len - 1 : -1] if len(self.screenshots) > 1 else []

            for idx in range(history_len):
                if idx < len(history_screenshots):
                    screenshot_b64 = history_screenshots[idx]
                    content = [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
                    ]
                    if idx == 0:
                        content.append({"type": "text", "text": instruction_prompt})
                    self.messages.append({"role": "user", "content": content})

                self.messages.append({"role": "assistant", "content": [{"type": "text", "text": history_responses[idx]}]})
            self.messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{processed_image}"}},
                    ],
                }
            )
        else:
            self.messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{processed_image}"}},
                        {"type": "text", "text": instruction_prompt},
                    ],
                }
            )

        # Call LLM via litellm
        completion_kwargs = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        # Only pass max_tokens when explicitly configured. Omitting lets vLLM
        # compute output budget from (max_model_len - input_tokens); passing
        # a value equal to max_model_len triggers VLLMValidationError.
        if self.max_tokens is not None:
            completion_kwargs["max_tokens"] = self.max_tokens
        if self.top_k is not None:
            # Pass top_k via extra_body so OpenAI-compatible vLLM endpoints honor it.
            completion_kwargs["extra_body"] = {"top_k": self.top_k}

        if self.api_key:
            completion_kwargs["api_key"] = self.api_key
        if self.base_url:
            completion_kwargs["base_url"] = self.base_url

        self._dump_llm_request(completion_kwargs, current_step, screenshot, (original_width, original_height), (processed_width, processed_height))

        response = litellm.completion(**completion_kwargs)
        self.last_telemetry.record_litellm_response(response, model=self.model)

        response_message = response.choices[0].message
        response_text = response_message.content or ""

        # Store response in history
        self.responses.append(response_text)

        self.logger.debug(f"Qwen3VL Output: {response_text}")

        # Parse the response (OSWorld style)
        thought, action_type, action_args, raw_action_args = self._parse_response(response_text, original_width, original_height, processed_width, processed_height)

        self.logger.info(f"Parsed - Thought: {thought}, Action: {action_type}")
        self.logger.info(f"Raw model args: {raw_action_args}")
        self.logger.info(f"Execution args: {action_args}")
        if raw_action_args != action_args:
            print(f"  Raw Params: {raw_action_args}")
            print(f"  Exec Params: {action_args}")

        # Store action description
        self.actions.append(f"{action_type}: {thought}" if thought else action_type)
        self.action_records.append({"action_type": action_type, "params": action_args, "raw_params": raw_action_args, "thought": thought})

        # Build response JSON
        if not action_type:
            # Fallback - couldn't parse action
            response_json = json.dumps(
                {
                    "status": "error",
                    "output": [{"type": "reasoning", "summary": [{"text": response_text}]}, {"type": "message", "content": [{"type": "output_text", "text": "Could not parse action from response."}]}],
                }
            )
        elif action_type == "terminate":
            # Terminal action
            status = action_args.get("status", "success")
            response_json = json.dumps(
                {"status": "completed", "output": [{"type": "reasoning", "summary": [{"text": thought}]}, {"type": "message", "content": [{"type": "output_text", "text": f"DONE. Task {status}."}]}]}
            )
        elif action_type == "wait":
            wait_time = action_args.get("time", 5)
            response_json = json.dumps(
                {"status": "completed", "output": [{"type": "reasoning", "summary": [{"text": thought}]}, {"type": "computer_call", "action": {"type": "wait", "duration": wait_time}}]}
            )
        else:
            action_dict = {"type": action_type}
            action_dict.update(action_args)

            response_json = json.dumps({"status": "completed", "output": [{"type": "reasoning", "summary": [{"text": thought}]}, {"type": "computer_call", "action": action_dict}]})

        self.logger.debug(f"Response JSON: {response_json}")

        # Parse response into an Action using the Qwen3-VL action space.
        action = self.action_space.parse_response(response_json)

        self.logger.debug(f"Qwen3VL agent returned action: {action.action_type}")

        return action

    def reset(self) -> None:
        """
        Reset agent state for a new task.

        Clears conversation history.
        """
        self.logger.debug("Resetting Qwen3VL agent")
        self.messages = [{"role": "system", "content": [{"type": "text", "text": self.system_prompt}]}]
        self.screenshots = []
        self.responses = []
        self.actions = []
        self.action_records = []
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
        self.logger.debug("Closed Qwen3VL agent")
