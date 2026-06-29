"""Claude-based task proposal agent for ppteval."""

import json
from typing import Any

from ppteval.action_spaces.claude import ClaudeActionSpace
from ppteval.agents.claude_agent import ClaudeAgent
from ppteval.config import ClaudeConfig
from ppteval.core.base import Action
from ppteval.utils.task_proposal import add_tasks_to_dataset

TASK_PROPOSER_SYSTEM_PROMPT = """<SYSTEM_CAPABILITY>
We are creating a dataset of tasks to benchmark computer-use agents on Microsoft Office tasks.
You are a helpful task-proposal agent who will explore the current open file and find interesting,
realistic and feasible tasks to add to the dataset.
Include tasks of varying difficulty and styles. Once you have finished thoroughly exploring the file
and proposing tasks, call the function "finish" with a message to the user with a reason for finishing.
* You are utilising an Ubuntu virtual machine with internet access.
</SYSTEM_CAPABILITY>"""


class ClaudeTaskProposerActionSpace(ClaudeActionSpace):
    """Claude action space that records proposed tasks as a side effect."""

    def parse_response(self, response: str | dict) -> Action:
        response_data = json.loads(response) if isinstance(response, str) else response

        for item in response_data.get("output", []):
            if item.get("type") not in {"call", "computer_call"}:
                continue
            action_data = item.get("action", {})
            if action_data.get("type") != "add_tasks_to_dataset":
                continue

            tasks = action_data.get("tasks", [])
            if isinstance(tasks, list):
                add_tasks_to_dataset([str(task) for task in tasks])
            return Action(
                action_type="wait",
                params={"duration": 0.1},
                reasoning=f"Added {len(tasks)} proposed tasks to the dataset.",
            )

        return super().parse_response(response_data)


class ClaudeTaskProposer(ClaudeAgent):
    """Claude agent with an extra tool for collecting task proposals."""

    def __init__(self, config: dict[str, Any] | ClaudeConfig | str | None = None):
        super().__init__(config)
        self.action_space = ClaudeTaskProposerActionSpace()
        self.tools.append(
            {
                "type": "function",
                "function": {
                    "name": "add_tasks_to_dataset",
                    "description": "Add a list of tasks to the dataset.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tasks": {
                                "type": "array",
                                "description": "A list of tasks to add to the dataset.",
                                "items": {"type": "string"},
                            }
                        },
                    },
                },
            }
        )
        self.messages = [
            {
                "role": "system",
                "content": TASK_PROPOSER_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
