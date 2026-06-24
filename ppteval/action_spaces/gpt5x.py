"""
GPT-5.x (GA `computer` tool) action space.

Extends CUAActionSpace with support for modifier key holds (`keydown`/`keyup`)
that the GA `computer` tool requires when mouse actions carry a `keys` field.
Key name normalization (e.g. ``ctrl`` -> ``Control_L``) is performed via
``xdotool`` so the sandbox can hold the key for the duration of a mouse
action.
"""

from __future__ import annotations

from typing import Any

from ppteval.action_spaces.cua import CUAActionSpace


# Map of agent-emitted key names to xdotool keysyms.
_XDOTOOL_KEY_MAP = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "meta": "super",
    "cmd": "super",
    "command": "super",
    "super": "super",
    "win": "super",
    "enter": "Return",
    "return": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "tab": "Tab",
    "backspace": "BackSpace",
    "delete": "Delete",
    "space": "space",
    "arrowleft": "Left",
    "arrowright": "Right",
    "arrowup": "Up",
    "arrowdown": "Down",
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
}


def _xdotool_key(name: str) -> str:
    """Normalize an agent key name to an xdotool keysym."""
    if not isinstance(name, str):
        return str(name)
    key = name.strip()
    lowered = key.lower()
    return _XDOTOOL_KEY_MAP.get(lowered, key)


class GPT5xActionSpace(CUAActionSpace):
    """Action space for the GA `computer` tool used by GPT-5.x agents."""

    # Mouse action types that can carry a `keys` modifier list.
    MOUSE_ACTIONS_WITH_KEYS = {"click", "double_click", "drag", "move", "scroll"}

    @classmethod
    def expand_modifier_keys(cls, action: dict[str, Any]) -> list[dict[str, Any]]:
        """Expand a single batched mouse action that carries ``keys`` modifiers
        into a ``[keydown..., action_without_keys, keyup...]`` triple.

        Mouse actions without ``keys`` (or with an empty list) are returned as
        a singleton list with ``keys`` stripped — the sandbox does not accept
        ``keys`` as a kwarg on its click/move/scroll/drag methods. Non-mouse
        actions are returned unchanged.
        """
        if not isinstance(action, dict):
            return [action]

        action_type = action.get("type")
        if action_type not in cls.MOUSE_ACTIONS_WITH_KEYS:
            return [action]

        keys = action.get("keys")
        # Always strip `keys`: the sandbox click/move/etc. methods don't accept it.
        stripped = {k: v for k, v in action.items() if k != "keys"}
        if not keys:
            return [stripped]

        keydowns = [{"type": "keydown", "key": k} for k in keys]
        keyups = [{"type": "keyup", "key": k} for k in reversed(keys)]
        return [*keydowns, stripped, *keyups]

    def _execute_single(self, sandbox: Any, action: Any) -> Any:
        """Execute a single GPT-5.x action, adding keydown/keyup support via xdotool."""
        action_type = action.action_type
        if action_type in ("keydown", "keyup"):
            self.sandbox = sandbox
            key = action.params.get("key") or action.params.get("keys")
            if isinstance(key, list):
                key = key[0] if key else ""
            keysym = _xdotool_key(key)
            cmd = f"xdotool {action_type} {keysym}"
            return sandbox.execute_command(cmd)
        return super()._execute_single(sandbox, action)
