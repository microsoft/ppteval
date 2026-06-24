"""Prompt templates for the native ppteval OpenCUA agent."""

from __future__ import annotations

import random

_TRIPLE_CLICK_FUNC = (
    '{"name": "computer.triple_click", "description": "Triple click on the screen", '
    '"parameters": {"type": "object", "properties": '
    '{"x": {"type": "number", "description": "The x coordinate of the triple click"}, '
    '"y": {"type": "number", "description": "The y coordinate of the triple click"}}, '
    '"required": ["x", "y"]}}'
)

_TERMINATE_FUNC_V1 = (
    '{"name": "computer.terminate", '
    '"description": "Terminate the current task and report its completion status", '
    '"parameters": {"type": "object", "properties": '
    '{"status": {"type": "string", "enum": ["success", "fail"], '
    '"description": "The status of the task"}}, "required": ["status"]}}'
)

_TERMINATE_FUNC_V1_FAILURE = (
    '{"name": "computer.terminate", '
    '"description": "Terminate the current task and report its completion status", '
    '"parameters": {"type": "object", "properties": '
    '{"status": {"type": "string", "enum": ["success", "failure"], '
    '"description": "The status of the task"}}, "required": ["status"]}}'
)

SYSTEM_PROMPT_V1_L1 = f"""You are a GUI agent solving PowerPoint tasks. You are given a task and a screenshot of the screen.
You need to perform a series of pyautogui actions to complete the task.

For each step, provide your response in this format:

Action:
  Provide clear, concise, and actionable instructions:
  - If the action involves interacting with a specific target:
    - Describe target explicitly without using coordinates
    - Specify element names when possible
    - Describe features (shape, color, position) if name unavailable
  - If the action involves keyboard actions like press, write, or hotkey:
    - Consolidate repetitive keypresses with count
    - Specify expected text outcome for typing actions

Finally, output the action as PyAutoGUI code or the following functions:
- {_TRIPLE_CLICK_FUNC}
- {_TERMINATE_FUNC_V1}""".strip()

SYSTEM_PROMPT_V1_L2 = """You are a GUI agent solving PowerPoint tasks. You are given a task and a screenshot of the screen.
You need to perform a series of pyautogui actions to complete the task.
The password of the computer is "{password}".
If the task is not possible to do, output the action computer.terminate(status='failure').

For each step, provide your response in this format:

Thought:
  - Step by Step Progress Assessment:
    - Analyze completed task parts and their contribution to the overall goal
    - Reflect on potential errors, unexpected results, or obstacles
    - If previous action was incorrect, predict a logical recovery step
  - Next Action Analysis:
    - List possible next actions based on current state
    - Evaluate options considering current state and previous actions
    - Propose most logical next action
    - Anticipate consequences of the proposed action
  - For Text Input Actions:
    - Note current cursor position
    - Consolidate repetitive actions
    - Describe expected final text outcome
  - Use first-person perspective in reasoning

Action:
  Provide clear, concise, and actionable instructions:
  - If the action involves interacting with a specific target:
    - Describe target explicitly without using coordinates
    - Specify element names when possible
    - Describe features (shape, color, position) if name unavailable
  - If the action involves keyboard actions like press, write, or hotkey:
    - Consolidate repetitive keypresses with count
    - Specify expected text outcome for typing actions

Finally, output the action as PyAutoGUI code or the following functions:
- {triple_click_func}
- {terminate_func}""".format(
    password="{password}",
    triple_click_func=_TRIPLE_CLICK_FUNC.replace("{", "{{").replace("}", "}}"),
    terminate_func=_TERMINATE_FUNC_V1_FAILURE.replace("{", "{{").replace("}", "}}"),
)

SYSTEM_PROMPT_V1_L3 = f"""You are a GUI agent solving PowerPoint tasks. You are given a task and a screenshot of the screen.
You need to perform a series of pyautogui actions to complete the task.

For each step, provide your response in this format:

Observation:
  - Describe the current computer state based on the full screenshot in detail.
  - Describe content, elements, options, information, or clues relevant to the task goal.

Thought:
  - Assess progress and decide the next action.
  - Use first-person perspective in reasoning.

Action:
  Provide clear, concise, and actionable instructions without using coordinates.

Finally, output the action as PyAutoGUI code or the following functions:
- {_TRIPLE_CLICK_FUNC}
- {_TERMINATE_FUNC_V1_FAILURE}""".strip()

GENERAL_COMPUTER_INSTRUCTIONS = [
    """You are a GUI agent solving PowerPoint tasks. You are given a task, a screenshot of the screen and your previous interactions with the computer. You need to perform a series of actions to complete the task. The password of the computer is "{password}", use it when you need sudo rights. You need to wait explicitly for installation, website loading, or running commands to finish. Do not terminate the task unless you are sure the task is finished. If you cannot finish the task exactly as instructed, report failure.""",
]

L3_FORMAT_INSTRUCTION = """For each step, provide your response in this format:
# Step: {step number}
## Observation:
{observation}
## Thought:
{thought}
## Action:
{action}
## Code:
{code}"""

L2_FORMAT_INSTRUCTION = """For each step, provide your response in this format:
# Step: {step number}
## Thought:
{thought}
## Action:
{action}
## Code:
{code}"""

L1_FORMAT_INSTRUCTION = """For each step, provide your response in this format:
# Step: {step number}
## Action:
{action}
## Code:
{code}"""

OBSERVATION_INSTRUCTIONS = [
    """For the Observation section, describe the current computer state based on the full screenshot in detail, including the active application, visible controls, text fields, dialogs, loading states, and any clues relevant to the task.""",
]

THOUGHT_INSTRUCTIONS = [
    """For the Thought section, reflect on previous actions, assess progress toward the task, propose the most logical next action, and explain why it is best. Use first-person perspective.""",
]

ACTION_INSTRUCTIONS = [
    """For the Action section, provide clear, concise, and actionable instructions in one sentence. Do not use coordinates; describe targets by label, visual traits, or relative position. For keyboard actions, consolidate repeated keypresses and specify expected text.""",
]

_WAIT_FUNC = (
    '{"name": "computer.wait", '
    '"description": "Make the computer wait for 20 seconds for installation, running code, etc.", '
    '"parameters": {"type": "object", "properties": {}, "required": []}}'
)

_TERMINATE_FUNC_V2 = (
    '{"name": "computer.terminate", '
    '"description": "Terminate the current task and report its completion status", '
    '"parameters": {"type": "object", "properties": {'
    '"status": {"type": "string", "enum": ["success", "failure"], '
    '"description": "The status of the task"}, '
    '"answer": {"type": "string", "description": "The answer of the task"}}, '
    '"required": ["status"]}}'
)

CODE_INSTRUCTION = f"""For the code section, output the corresponding code for the action.
The code should be either PyAutoGUI code or one of the following functions wrapped in a code block:
- {_WAIT_FUNC}
- {_TERMINATE_FUNC_V2}
Examples:
```python
pyautogui.click(x=123, y=456)
```
```code
computer.terminate(status="success")
```"""

SYSTEM_PROMPT_V2_L1 = """
{general_computer_instruction}

{format_instruction}

{action_instruction}

{code_instruction}
""".strip()

SYSTEM_PROMPT_V2_L2 = """
{general_computer_instruction}

{format_instruction}

{thought_instruction}

{action_instruction}

{code_instruction}
""".strip()

SYSTEM_PROMPT_V2_L3 = """
{general_computer_instruction}

{format_instruction}

{observation_instruction}

{thought_instruction}

{action_instruction}

{code_instruction}
""".strip()


def build_sys_prompt(level: str, password: str = "password", use_random: bool = False) -> str:
    """Build the system prompt for OpenCUA."""
    general = random.choice(GENERAL_COMPUTER_INSTRUCTIONS) if use_random else GENERAL_COMPUTER_INSTRUCTIONS[0]
    action = random.choice(ACTION_INSTRUCTIONS) if use_random else ACTION_INSTRUCTIONS[0]
    thought = random.choice(THOUGHT_INSTRUCTIONS) if use_random else THOUGHT_INSTRUCTIONS[0]
    observation = random.choice(OBSERVATION_INSTRUCTIONS) if use_random else OBSERVATION_INSTRUCTIONS[0]

    if level == "l1":
        return SYSTEM_PROMPT_V2_L1.format(
            general_computer_instruction=general.format(password=password),
            format_instruction=L1_FORMAT_INSTRUCTION,
            action_instruction=action,
            code_instruction=CODE_INSTRUCTION,
        )
    if level == "l2":
        return SYSTEM_PROMPT_V2_L2.format(
            general_computer_instruction=general.format(password=password),
            format_instruction=L2_FORMAT_INSTRUCTION,
            thought_instruction=thought,
            action_instruction=action,
            code_instruction=CODE_INSTRUCTION,
        )
    if level == "l3":
        return SYSTEM_PROMPT_V2_L3.format(
            general_computer_instruction=general.format(password=password),
            format_instruction=L3_FORMAT_INSTRUCTION,
            observation_instruction=observation,
            thought_instruction=thought,
            action_instruction=action,
            code_instruction=CODE_INSTRUCTION,
        )
    raise ValueError("Invalid level. Choose from 'l1', 'l2', or 'l3'.")


STEP_TEMPLATE = "# Step {step_num}:\n"
INSTRUCTION_TEMPLATE = (
    "# Task Instruction:\n{instruction}\n\n"
    "Please generate the next move according to the screenshot, task instruction and previous steps (if provided).\n"
)

ACTION_HISTORY_TEMPLATE = "## Action:\n{action}\n"
THOUGHT_HISTORY_TEMPLATE = "## Thought:\n{thought}\n\n## Action:\n{action}\n"
OBSERVATION_HISTORY_TEMPLATE = "## Observation:\n{observation}\n\n## Thought:\n{thought}\n\n## Action:\n{action}\n"
