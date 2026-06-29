"""Unit tests for ScreenEnv-backed action spaces."""

from unittest.mock import Mock, patch

from ppteval.action_spaces import (
    ClaudeActionSpace,
    CUAActionSpace,
    OpenCUAActionSpace,
    Qwen3VLActionSpace,
    UITARSActionSpace,
)
from ppteval.core.base import Action


def make_sandbox() -> Mock:
    """Create a fake sandbox with the methods used by the executor."""
    sandbox = Mock()
    sandbox.left_click = Mock()
    sandbox.right_click = Mock()
    sandbox.write = Mock()
    sandbox.press = Mock()
    sandbox.move_mouse = Mock()
    sandbox.scroll = Mock()
    sandbox.wait = Mock()
    sandbox.drag = Mock()
    sandbox.execute_command = Mock()
    sandbox.execute_python_command = Mock()
    return sandbox


def test_cua_action_space_executes_click_via_screenenv_click():
    sandbox = make_sandbox()

    CUAActionSpace().execute(sandbox, Action("click", {"x": 10, "y": 20, "button": "right"}))

    sandbox.right_click.assert_called_once_with(x=10, y=20)


def test_claude_action_space_executes_click_via_xdotool():
    sandbox = make_sandbox()

    ClaudeActionSpace().execute(sandbox, Action("left_click", {"coordinate": [10, 20]}))

    sandbox.execute_command.assert_called_once_with("xdotool mousemove --sync 10 20 click 1")
    sandbox.left_click.assert_not_called()


def test_executes_type_as_write():
    sandbox = make_sandbox()

    CUAActionSpace().execute(sandbox, Action("type", {"text": "hello"}))

    sandbox.write.assert_called_once_with(text="hello")


def test_executes_keypress_as_press():
    sandbox = make_sandbox()

    CUAActionSpace().execute(sandbox, Action("keypress", {"keys": ["ctrl", "c"]}))

    sandbox.press.assert_called_once_with(key=["ctrl", "c"])


def test_claude_action_space_executes_key_via_xdotool():
    sandbox = make_sandbox()

    ClaudeActionSpace().execute(sandbox, Action("key", {"text": "ctrl+c"}))

    sandbox.execute_command.assert_called_once_with("xdotool key ctrl+c")
    sandbox.press.assert_not_called()


def test_executes_directional_scroll():
    sandbox = make_sandbox()

    CUAActionSpace().execute(sandbox, Action("scroll", {"direction": "down", "amount": 5}))

    sandbox.scroll.assert_called_once_with(direction="down", amount=5)


def test_executes_cua_scroll_wheel_delta():
    sandbox = make_sandbox()

    CUAActionSpace().execute(sandbox, Action("scroll", {"scroll_y": 2, "scroll_x": -1}))

    sandbox.execute_command.assert_any_call("xdotool click --repeat 2 5")
    sandbox.execute_command.assert_any_call("xdotool click --repeat 1 6")


def test_uitars_action_space_uses_cua_style_scroll_steps():
    sandbox = make_sandbox()

    UITARSActionSpace().execute(sandbox, Action("scroll", {"scroll_y": 10, "scroll_x": 0}))

    sandbox.execute_command.assert_called_once_with("xdotool click --repeat 1 5")


def test_claude_action_space_scroll_keeps_modifier_and_position():
    sandbox = make_sandbox()

    ClaudeActionSpace().execute(
        sandbox,
        Action(
            "scroll",
            {
                "coordinate": [100, 200],
                "scroll_direction": "down",
                "scroll_amount": 3,
                "text": "ctrl",
            },
        ),
    )

    sandbox.execute_command.assert_called_once_with(
        "xdotool mousemove --sync 100 200 keydown ctrl click --repeat 3 5 keyup ctrl"
    )


def test_qwen_action_space_executes_scroll_with_legacy_direction():
    sandbox = make_sandbox()

    Qwen3VLActionSpace().execute(sandbox, Action("scroll", {"pixels": 3}))

    sandbox.execute_command.assert_called_once_with("xdotool click --repeat 3 4")


def test_qwen_action_space_executes_key_with_mapped_chord():
    sandbox = make_sandbox()

    Qwen3VLActionSpace().execute(sandbox, Action("key", {"keys": ["ctrl", "C"]}))

    sandbox.execute_command.assert_called_once_with("xdotool key ctrl+c")


def test_claude_wait_uses_python_sleep_not_sandbox_wait():
    sandbox = make_sandbox()

    with patch("ppteval.action_spaces.claude.time.sleep") as sleep:
        ClaudeActionSpace().execute(sandbox, Action("wait", {"duration": 2}))

    sleep.assert_called_once_with(2)
    sandbox.wait.assert_not_called()


def test_cua_wait_uses_sandbox_wait_in_milliseconds():
    sandbox = make_sandbox()

    CUAActionSpace().execute(sandbox, Action("wait", {"duration": 2}))

    sandbox.wait.assert_called_once_with(2000)


def test_executes_drag_path():
    sandbox = make_sandbox()

    CUAActionSpace().execute(
        sandbox,
        Action("drag", {"path": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]})
    )

    sandbox.drag.assert_called_once_with((1, 2), (3, 4))


def test_qwen_action_space_executes_left_click_drag():
    sandbox = make_sandbox()

    Qwen3VLActionSpace().execute(sandbox, Action("left_click_drag", {"coordinate": [30, 40]}))

    sandbox.execute_command.assert_called_once_with("xdotool mousedown 1 mousemove --sync 30 40 mouseup 1")


def test_qwen_wait_uses_python_sleep_not_sandbox_wait():
    sandbox = make_sandbox()

    with patch("ppteval.action_spaces.qwen3vl.time.sleep") as sleep:
        Qwen3VLActionSpace().execute(sandbox, Action("wait", {"time": 3}))

    sleep.assert_called_once_with(3)
    sandbox.wait.assert_not_called()


def test_opencua_action_space_executes_pyautogui_code():
    sandbox = make_sandbox()

    OpenCUAActionSpace().execute(sandbox, Action("pyautogui", {"code": "```python\npyautogui.click()\n```"}))

    sandbox.execute_python_command.assert_called_once_with(
        import_prefix=["pyautogui"],
        command="pyautogui.click()",
    )


def test_opencua_wait_defaults_to_legacy_twenty_seconds():
    sandbox = make_sandbox()

    with patch("ppteval.action_spaces.opencua.time.sleep") as sleep:
        result = OpenCUAActionSpace().execute(sandbox, Action("wait", {}))

    sleep.assert_called_once_with(20)
    sandbox.wait.assert_not_called()
    assert result == "Waited for 20 seconds"
