"""ppteval: A refactored architecture for PowerPoint agent evaluation."""

__version__ = "0.1.0"

# Core imports
from ppteval.core import (
    State,
    GUIState,
    ExtendedGUIState,
    APIState,
    WorkspaceState,
    Action,
    ActionSpace,
    Environment,
    Agent,
    Grader,
    EvaluationResult,
    TaskResult,
)

from ppteval.core.task import Task, TaskRegistry

# Config imports
from ppteval.config import (
    DisplaySize,
    EnvironmentConfig,
    CUAConfig,
    GPT5xConfig,
    ClaudeConfig,
    UITARSConfig,
    UITARSVLLMConfig,
    GeminiConfig,
    Qwen3VLConfig,
    Qwen3VLOSWorldConfig,
    OpenCUAConfig,
    OrchestratorConfig,
    CLIAgentConfig,
)

# Environment imports (ScreenEnvEnvironment is loaded lazily to avoid
# requiring Docker for CLI-only workflows).
from ppteval.environments import CLIWorkspaceEnvironment

from ppteval.action_spaces import (
    CUAActionSpace,
    GPT5xActionSpace,
    ClaudeActionSpace,
    UITARSActionSpace,
    GeminiActionSpace,
    Qwen3VLActionSpace,
    OpenCUAActionSpace,
)

# Agent imports
from ppteval.agents import (
    CUAAgent,
    GPT5xAgent,
    ClaudeAgent,
    ClaudeTaskProposer,
    UITARSAgent,
    UITARSVLLMAgent,
    Qwen3VLAgent,
    Qwen3VLOSWorldAgent,
    OpenCUAAgent,
    CLIAgent,
    ClaudeCodeAgent,
    CopilotCLIAgent,
    CodexCLIAgent,
)

# Orchestrator import
from ppteval.orchestrator import Orchestrator

__all__ = [
    # Core
    "State",
    "GUIState",
    "ExtendedGUIState",
    "APIState",
    "WorkspaceState",
    "Action",
    "ActionSpace",
    "Environment",
    "Agent",
    "Grader",
    "EvaluationResult",
    "TaskResult",
    # Task
    "Task",
    "TaskRegistry",
    # Config
    "DisplaySize",
    "EnvironmentConfig",
    "CUAConfig",
    "GPT5xConfig",
    "ClaudeConfig",
    "UITARSConfig",
    "UITARSVLLMConfig",
    "GeminiConfig",
    "Qwen3VLConfig",
    "Qwen3VLOSWorldConfig",
    "OpenCUAConfig",
    "OrchestratorConfig",
    "CLIAgentConfig",
    # Environments
    "ScreenEnvEnvironment",
    "CLIWorkspaceEnvironment",
    # Action spaces
    "CUAActionSpace",
    "GPT5xActionSpace",
    "ClaudeActionSpace",
    "UITARSActionSpace",
    "GeminiActionSpace",
    "Qwen3VLActionSpace",
    "OpenCUAActionSpace",
    # Agents
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
    "ClaudeCodeAgent",
    "CopilotCLIAgent",
    "CodexCLIAgent",
    # Orchestrator
    "Orchestrator",
]


def __getattr__(name):
    if name == "ScreenEnvEnvironment":
        from ppteval.environments import ScreenEnvEnvironment
        return ScreenEnvEnvironment
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
