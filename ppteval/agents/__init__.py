"""
PPTEval agent implementations.

Provides implementations for release-supported agent types (CUA, Claude, UITARS, Qwen3VL, OpenCUA)
that integrate with the ppteval Agent interface.
"""

from ppteval.agents.cua_agent import CUAAgent
from ppteval.agents.gpt5x_agent import GPT5xAgent
from ppteval.agents.claude_agent import ClaudeAgent
from ppteval.agents.claude_task_proposer import ClaudeTaskProposer
from ppteval.agents.uitars_agent import UITARSAgent
from ppteval.agents.uitars_vllm_agent import UITARSVLLMAgent
from ppteval.agents.qwen3vl_agent import Qwen3VLAgent
from ppteval.agents.qwen3vlosworld_agent import Qwen3VLOSWorldAgent
from ppteval.agents.opencua_agent import OpenCUAAgent
from ppteval.agents.cli import (
    CLIAgent,
    CLITelemetry,
    ClaudeCodeAgent,
    CopilotCLIAgent,
    CodexCLIAgent,
)

__all__ = [
    "CUAAgent",
    "GPT5xAgent",
    "ClaudeAgent",
    "ClaudeTaskProposer",
    "UITARSAgent",
    "UITARSVLLMAgent",
    "Qwen3VLAgent",
    "Qwen3VLOSWorldAgent",
    "OpenCUAAgent",
    "CLIAgent",
    "CLITelemetry",
    "ClaudeCodeAgent",
    "CopilotCLIAgent",
    "CodexCLIAgent",
]
