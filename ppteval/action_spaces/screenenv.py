"""Shared helpers for ScreenEnv-backed action spaces."""

from __future__ import annotations

import logging
from typing import Any

from ppteval.core.base import Action, GUIState, State, ActionSpace


logger = logging.getLogger(__name__)


class BaseScreenEnvActionSpace(ActionSpace):
    """Base action space with common ScreenEnv execution helpers."""

    def parse_response(self, response: str | dict) -> Action:
        """Parse agent response into an Action."""
        raise NotImplementedError

    def format_state(self, state: State) -> Any:
        """Default GUI state formatter for screenshot-based agents."""
        if not isinstance(state, GUIState):
            raise ValueError(f"Expected GUIState, got {type(state)}")
        return state.screenshot

    def execute(self, sandbox: Any, action: Action) -> Any:
        """Execute an Action against the sandbox.

        If ``action.sub_actions`` is set, this is a composite batch: run each
        child in order via ``_execute_single`` and stop early on a terminal
        child (per the OpenAI computer-use contract, the harness captures one
        screenshot AFTER the batch finishes; mid-batch ``screenshot`` requests
        are no-ops because they'd be redundant with that post-batch capture).
        """
        if action.sub_actions:
            result: Any = None
            for i, sub in enumerate(action.sub_actions):
                if sub.action_type == "screenshot":
                    # Skip: env captures one screenshot after the batch.
                    continue
                if sub.is_terminal():
                    logger.debug(
                        f"Batch: terminal sub-action {sub.action_type} at index {i}; stopping"
                    )
                    break
                try:
                    result = self._execute_single(sandbox, sub)
                except Exception as e:
                    logger.error(
                        f"Batch: sub-action {i} ({sub.action_type}) failed: {e}; "
                        f"aborting remaining {len(action.sub_actions) - i - 1} sub-action(s)"
                    )
                    break
            return result
        return self._execute_single(sandbox, action)

    def _execute_single(self, sandbox: Any, action: Action) -> Any:
        """Execute a single (non-composite) Action. Override in subclasses."""
        self.sandbox = sandbox
        action_type = action.action_type
        args = action.params.copy()

        if action_type == "computer":
            action_type = args.pop("action")

        if action_type in {"finish", "give_up", "terminate"}:
            return None

        if action_type == "pyautogui":
            return self._execute_pyautogui_code(args.get("code", ""))

        if action_type == "screenshot":
            return None

        if action_type == "move":
            action_type = "move_mouse"

        return self._dispatch_screenenv(action_type, args)

    def _dispatch_screenenv(self, action_type: str, args: dict[str, Any]) -> Any:
        self._normalize_coordinate_args(args)
        if hasattr(self.sandbox, action_type):
            method = getattr(self.sandbox, action_type)
            return method(**args)
        raise AttributeError(f"Sandbox does not have action '{action_type}'")

    def _execute_pyautogui_code(self, code: str) -> Any:
        code = code.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)
        return self.sandbox.execute_python_command(import_prefix=["pyautogui"], command=code)

    def _normalize_coordinate_args(self, args: dict[str, Any]) -> None:
        if "coordinate" in args and ("x" not in args or "y" not in args):
            x, y = self._coerce_coordinate(args.pop("coordinate"))
            args["x"] = x
            args["y"] = y

    @staticmethod
    def _coerce_coordinate(value: Any) -> tuple[int, int]:
        if isinstance(value, dict):
            return int(value.get("x", 0)), int(value.get("y", 0))
        return int(value[0]), int(value[1])

