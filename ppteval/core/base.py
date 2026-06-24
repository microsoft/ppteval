"""
Core base classes for ppteval.

This module defines the fundamental abstractions for the evaluation framework:
- State hierarchy (State, GUIState, ExtendedGUIState, APIState)
- Action (agent actions with type safety)
- Environment (base interface for task execution environments)
- Agent (base interface for agents)
- ActionSpace (formats state, parses agent outputs, and executes Actions)
- Grader (evaluates task completion)
- Result classes (EvaluationResult, TaskResult)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============ State Hierarchy ============

@dataclass
class State(ABC):
    """Base state returned by environments"""
    done: bool


@dataclass
class GUIState(State):
    """State for GUI-based environments"""
    screenshot: bytes


@dataclass
class ExtendedGUIState(GUIState):
    """Extended GUI state with additional context"""
    accessibility_tree: dict[str, Any] | None = None
    dom: dict[str, Any] | None = None


@dataclass
class APIState(State):
    """State for API-based environments (future)"""
    workspace_path: Path
    available_files: list[Path]
    last_operation_result: dict[str, Any] | None = None


@dataclass
class WorkspaceState(State):
    """State for filesystem-workspace-based environments (CLI agents).

    The agent operates by spawning an external CLI process that reads/writes
    files in ``workspace_dir``. The orchestrator does NOT step a per-action
    loop here — the CLI runs its own internal multi-turn loop. ``done`` flips
    to True once the CLI exits and the environment has verified the output.
    """
    workspace_dir: Path
    instruction: str
    input_files: list[Path] = field(default_factory=list)
    expected_output: Path | None = None
    cli_result: dict[str, Any] | None = None  # populated after CLI exits


# ============ Action ============

@dataclass
class Action:
    """Agent action with type safety.

    When ``sub_actions`` is set, this Action is a *composite batch*: a single
    model decision that expanded into multiple primitive actions to run in
    order (e.g. GPT-5.x ``computer_call.actions[]``). The orchestrator still
    counts the composite as one step; the action space iterates the children.
    """
    action_type: str  # "click", "type", "scroll", "finish", "batch", etc.
    params: dict[str, Any]
    reasoning: str | None = None
    sub_actions: list["Action"] | None = None

    def is_terminal(self) -> bool:
        """Check if this action completes the task.

        A composite action is terminal if any of its sub-actions is terminal.
        """
        if self.action_type in ["finish", "give_up"]:
            return True
        if self.sub_actions:
            return any(sa.is_terminal() for sa in self.sub_actions)
        return False


# ============ Base Classes ============

class Environment(ABC):
    """Base environment interface"""

    @abstractmethod
    def setup(self) -> State:
        """Initialize environment and return initial state"""
        pass

    @abstractmethod
    def update(self, action: Action) -> State:
        """Apply action and return new state"""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """Cleanup resources"""
        pass

    @abstractmethod
    def download_artifacts(self) -> dict[str, Path]:
        """Download task artifacts for verification"""
        pass


class Agent(ABC):
    """Base agent interface"""

    @abstractmethod
    def step(self, state: State) -> Action:
        """Take a step given current state"""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset agent state for new task"""
        pass


class ActionSpace(ABC):
    """
    Defines an agent/model-specific action space.

    Each action space owns the full boundary between the model and the
    execution environment: state formatting, response parsing, and sandbox
    execution. This mirrors the legacy OfficeArena per-agent action pattern
    while preserving ppteval's typed ``Action`` loop.
    """

    @abstractmethod
    def parse_response(self, response: str | dict) -> Action:
        """Parse agent response into Action"""
        pass

    @abstractmethod
    def format_state(self, state: State) -> Any:
        """Format state for agent consumption"""
        pass

    @abstractmethod
    def execute(self, sandbox: Any, action: Action) -> Any:
        """Execute a parsed action against an environment sandbox"""
        pass

class Grader(ABC):
    """Base grader interface"""

    @abstractmethod
    def evaluate(self, artifacts: dict[str, Path]) -> 'EvaluationResult':
        """Evaluate task completion"""
        pass


# ============ Results ============

@dataclass
class EvaluationResult:
    """Grading result"""
    score: float
    success: bool
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """Complete task execution result"""
    task_id: str
    goal: str
    success: bool
    score: float | None

    # Execution info
    execution_status: str  # "success", "max_steps", "agent_error", "infrastructure_failure"
    agent_steps: int
    execution_time_seconds: float

    # Verification info
    verification_status: str  # "success", "failed", "error"
    evaluation_result: EvaluationResult | None = None

    # Error tracking
    error_message: str | None = None
    error_traceback: str | None = None

    # Artifacts
    screenshots_dir: Path | None = None
    final_file_path: Path | None = None
    # Source OneDrive path the live-session PPTX was edited under, e.g.
    # "tasks/{task_id}_{upload_ts}.pptx". Lets us trace local artifacts back
    # to the exact OneDrive blob without re-deriving timestamps.
    remote_file_path: str | None = None

    # CLI-agent telemetry (None for non-CLI agents)
    cli_telemetry: dict[str, Any] | None = None
    agent_turns: int | None = None        # CLI's own loop iterations (vs. agent_steps which is orchestrator-step count)
    num_tool_calls: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization"""
        result = {
            "task_id": self.task_id,
            "goal": self.goal,
            "success": self.success,
            "score": self.score,
            "execution_status": self.execution_status,
            "agent_steps": self.agent_steps,
            "execution_time_seconds": self.execution_time_seconds,
            "verification_status": self.verification_status,
            "error_message": self.error_message,
        }

        if self.evaluation_result:
            result["evaluation_details"] = {
                "score": self.evaluation_result.score,
                "success": self.evaluation_result.success,
                "reason": self.evaluation_result.reason,
                "details": self.evaluation_result.details,
            }

        if self.screenshots_dir:
            result["screenshots_dir"] = str(self.screenshots_dir)
        if self.final_file_path:
            result["final_file_path"] = str(self.final_file_path)
        if self.remote_file_path:
            result["remote_file_path"] = self.remote_file_path

        # CLI telemetry (only emitted when present)
        if self.cli_telemetry is not None:
            result["cli_telemetry"] = self.cli_telemetry
        if self.agent_turns is not None:
            result["agent_turns"] = self.agent_turns
        if self.num_tool_calls is not None:
            result["num_tool_calls"] = self.num_tool_calls
        if self.total_tokens is not None:
            result["total_tokens"] = self.total_tokens
        if self.cost_usd is not None:
            result["cost_usd"] = self.cost_usd

        return result
