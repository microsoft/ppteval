"""OpenCUA image and coordinate utilities for ppteval."""

from __future__ import annotations

import ast
import base64
import math
import re
from io import BytesIO
from typing import Optional, Tuple

from PIL import Image


def smart_resize(
    height: int,
    width: int,
    factor: int = 28,
    min_pixels: int = 56 * 56,
    max_pixels: int = 14 * 14 * 4 * 1280,
    max_aspect_ratio_allowed: Optional[float] = None,
    size_can_be_smaller_than_factor: bool = False,
) -> Tuple[int, int]:
    """Resize dimensions to match OpenCUA/Qwen image constraints."""
    if not size_can_be_smaller_than_factor and (height < factor or width < factor):
        raise ValueError(f"height:{height} or width:{width} must be larger than factor:{factor}")
    if max_aspect_ratio_allowed is not None and max(height, width) / min(height, width) > max_aspect_ratio_allowed:
        raise ValueError(f"absolute aspect ratio must be smaller than {max_aspect_ratio_allowed}")

    h_bar = max(1, round(height / factor)) * factor
    w_bar = max(1, round(width / factor)) * factor

    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = max(1, math.floor(height / beta / factor)) * factor
        w_bar = max(1, math.floor(width / beta / factor)) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor

    return h_bar, w_bar


def process_image_for_opencua(image_bytes: bytes) -> Tuple[str, int, int, int, int]:
    """Resize and encode a screenshot for OpenCUA model input."""
    image = Image.open(BytesIO(image_bytes))
    original_width, original_height = image.size

    resized_height, resized_width = smart_resize(
        height=original_height,
        width=original_width,
        factor=28,
        min_pixels=3136,
        max_pixels=12845056,
    )

    image = image.resize((resized_width, resized_height))
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    return (
        base64.b64encode(buffer.getvalue()).decode("utf-8"),
        original_width,
        original_height,
        resized_width,
        resized_height,
    )


def project_coordinate_to_absolute_scale(
    pyautogui_code: str,
    screen_width: int,
    screen_height: int,
    coordinate_type: str = "relative",
) -> str:
    """Project relative OpenCUA PyAutoGUI coordinates to absolute screen coordinates."""

    def _coordinate_projection(x: float, y: float, width: int, height: int, coord_type: str) -> Tuple[int, int]:
        if coord_type in {"absolute", "screen"}:
            return int(round(x)), int(round(y))
        if coord_type == "relative":
            return int(round(x * width)), int(round(y * height))
        if coord_type == "qwen25":
            resized_height, resized_width = smart_resize(
                height=height,
                width=width,
                factor=28,
                min_pixels=3136,
                max_pixels=12845056,
            )
            if 0 <= x <= 1 and 0 <= y <= 1:
                return int(round(x * resized_width)), int(round(y * resized_height))
            return int(x / resized_width * width), int(y / resized_height * height)
        raise ValueError(f"Invalid coordinate type: {coord_type}. Expected relative, qwen25, or absolute.")

    pattern = r"(pyautogui\.\w+\([^\)]*\))"
    matches = re.findall(pattern, pyautogui_code)
    new_code = pyautogui_code

    function_parameters = {
        "click": ["x", "y", "clicks", "interval", "button", "duration", "pause"],
        "rightClick": ["x", "y", "duration", "tween", "pause"],
        "middleClick": ["x", "y", "duration", "tween", "pause"],
        "doubleClick": ["x", "y", "interval", "button", "duration", "pause"],
        "tripleClick": ["x", "y", "interval", "button", "duration", "pause"],
        "moveTo": ["x", "y", "duration", "tween", "pause"],
        "dragTo": ["x", "y", "duration", "button", "mouseDownUp", "pause"],
        "scroll": ["clicks", "x", "y", "pause"],
    }

    for full_call in matches:
        func_match = re.match(r"(pyautogui\.\w+)\((.*)\)", full_call, re.DOTALL)
        if not func_match:
            continue

        func_name = func_match.group(1)
        args_str = func_match.group(2)

        try:
            parsed = ast.parse(f"func({args_str})").body[0].value
        except SyntaxError:
            return pyautogui_code

        func_base_name = func_name.split(".")[-1]
        param_names = function_parameters.get(func_base_name, [])
        args = {}

        for idx, arg in enumerate(parsed.args):
            if idx >= len(param_names):
                continue
            try:
                args[param_names[idx]] = ast.literal_eval(arg)
            except (ValueError, SyntaxError):
                continue

        try:
            for kw in parsed.keywords:
                try:
                    args[kw.arg] = ast.literal_eval(kw.value)
                except (ValueError, SyntaxError):
                    continue
        except Exception:
            return pyautogui_code

        if "x" not in args or "y" not in args:
            continue

        try:
            x_abs, y_abs = _coordinate_projection(float(args["x"]), float(args["y"]), screen_width, screen_height, coordinate_type)
        except ValueError:
            continue

        args["x"] = x_abs
        args["y"] = y_abs

        reconstructed_args = []
        for param_name in param_names:
            if param_name not in args:
                break
            arg_value = args[param_name]
            reconstructed_args.append(f"'{arg_value}'" if isinstance(arg_value, str) else str(arg_value))

        used_params = set(param_names[: len(reconstructed_args)])
        for kw in parsed.keywords:
            if kw.arg in used_params:
                continue
            arg_value = args.get(kw.arg)
            if arg_value is None:
                continue
            if isinstance(arg_value, str):
                reconstructed_args.append(f"{kw.arg}='{arg_value}'")
            else:
                reconstructed_args.append(f"{kw.arg}={arg_value}")

        new_call = f"{func_name}({', '.join(reconstructed_args)})"
        new_code = new_code.replace(full_call, new_call, 1)

    return new_code
