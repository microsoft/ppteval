"""Unit tests for OpenCUAActionSpace."""

from ppteval.action_spaces.opencua import OpenCUAActionSpace, parse_response_to_cot_and_action


def test_parse_pyautogui_action():
    response = {
        "output": [
            {"type": "reasoning", "summary": [{"text": "Use pyautogui"}]},
            {
                "type": "computer_call",
                "action": {"type": "pyautogui", "code": "pyautogui.click(10, 20)"},
            },
        ]
    }

    action = OpenCUAActionSpace().parse_response(response)

    assert action.action_type == "pyautogui"
    assert action.params == {"code": "pyautogui.click(10, 20)"}
    assert action.reasoning == "Use pyautogui"


def test_parse_wait_action():
    response = {
        "output": [
            {
                "type": "computer_call",
                "action": {"type": "wait", "duration": 20},
            }
        ]
    }

    action = OpenCUAActionSpace().parse_response(response)

    assert action.action_type == "wait"
    assert action.params == {"time": 20}


def test_parse_done_message_as_finish():
    response = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "DONE. Task completed."}],
            }
        ]
    }

    action = OpenCUAActionSpace().parse_response(response)

    assert action.action_type == "finish"
    assert action.reasoning == "DONE. Task completed."


def test_parse_raw_model_response_projects_pyautogui_coordinates():
    response = """## Thought:
I should click the target.
## Action:
Click the target.
```python
pyautogui.click(x=0.5, y=0.25)
```"""

    instruction, actions, sections = parse_response_to_cot_and_action(
        response,
        screen_size=(1000, 800),
        coordinate_type="relative",
    )

    assert instruction == "Click the target."
    assert actions == ["pyautogui.click(500, 200)"]
    assert sections["thought"] == "I should click the target."


def test_parse_raw_model_response_handles_terminate_success():
    response = """## Action:
Finish the task.
```code
computer.terminate(status="success")
```"""

    _, actions, sections = parse_response_to_cot_and_action(
        response,
        screen_size=(1000, 800),
        coordinate_type="relative",
    )

    assert actions == ["DONE"]
    assert sections["code"] == "DONE"


def test_parse_raw_model_response_accepts_v1_section_labels():
    response = """Thought:
I should wait for the UI to settle.
Action:
Wait.
```code
computer.wait()
```"""

    instruction, actions, sections = parse_response_to_cot_and_action(
        response,
        screen_size=(1000, 800),
        coordinate_type="relative",
    )

    assert instruction == "Wait."
    assert actions == ["WAIT"]
    assert sections["thought"] == "I should wait for the UI to settle."


def test_parse_raw_model_response_converts_computer_triple_click():
    response = """## Action:
Triple click the target.
```python
computer.triple_click(x=0.5, y=0.25)
```"""

    _, actions, sections = parse_response_to_cot_and_action(
        response,
        screen_size=(1000, 800),
        coordinate_type="relative",
    )

    assert actions == ["pyautogui.tripleClick(500, 200)"]
    assert sections["code"] == "pyautogui.tripleClick(500, 200)"


def test_parse_raw_model_response_projects_positioned_scroll():
    response = """## Action:
Scroll at the target.
```python
pyautogui.scroll(-5, x=0.5, y=0.25)
```"""

    _, actions, sections = parse_response_to_cot_and_action(
        response,
        screen_size=(1000, 800),
        coordinate_type="relative",
    )

    assert actions == ["pyautogui.scroll(-5, 500, 200)"]
    assert sections["code"] == "pyautogui.scroll(-5, 500, 200)"
