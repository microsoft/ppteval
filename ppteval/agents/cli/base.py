"""
Base class for CLI-driven agents (Claude Code, Copilot CLI, Codex CLI).

CLI agents differ from API agents in one key way: the CLI binary owns its
own multi-turn loop. So ``CLIAgent.step()`` is invoked exactly once by the
orchestrator, spawns the CLI as a subprocess in the task's workspace, waits
for it to exit, parses its emitted telemetry (turns, tool calls, tokens,
cost), and returns a single terminal ``Action`` that flips ``state.done``.

Subclasses implement three hooks:
    _build_command(prompt, workspace_dir) -> list[str]
    _build_prompt(state)                  -> str
    _parse_telemetry(run)                 -> CLITelemetry

All process invocation, transcript persistence, and timing are shared here.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ppteval.core.base import Action, Agent, State, WorkspaceState

logger = logging.getLogger(__name__)


@dataclass
class CLITelemetry:
    """Normalized telemetry across CLI agents.

    Fields are None when the underlying CLI does not emit them. Cost is
    always None for CLIs without an emitted dollar figure (e.g. Copilot CLI
    on a subscription).
    """
    num_turns: int | None = None
    num_tool_calls: int | None = None
    tool_calls_by_name: dict[str, int] = field(default_factory=dict)
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    model: str | None = None
    duration_seconds: float = 0.0
    cli_exit_code: int | None = None
    cli_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CLIRunResult:
    """Raw artifacts from a single CLI subprocess invocation."""
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    transcript_path: Path | None  # path to ndjson stream (if any)
    timed_out: bool = False


class CLIAgent(Agent):
    """Base class for filesystem-workspace CLI agents."""

    #: Identifies the CLI family (overridden in subclasses). Used for logging
    #: and for ``run_benchmark`` aggregation. Examples: "claude-code",
    #: "copilot-cli", "codex-cli".
    cli_name: str = "cli"

    #: Marker the orchestrator uses to switch to the single-step CLI path.
    kind: str = "cli"

    #: Env vars to drop before spawning. Subclasses extend.
    default_scrub_env: tuple[str, ...] = ()

    def __init__(self, config: Any | None = None):
        # ``config`` is a CLIAgentConfig dataclass instance OR a raw dict.
        if config is None:
            config = {}
        if hasattr(config, "__dict__") and not isinstance(config, dict):
            config_dict = dict(config.__dict__)
        else:
            config_dict = dict(config)
        self.config: dict[str, Any] = config_dict
        self.agent_config = config  # original instance retained for typed access

        self.binary: str = config_dict.get("binary") or self.cli_name
        self.extra_args: list[str] = list(config_dict.get("extra_args") or [])
        self.timeout_s: int = int(config_dict.get("timeout_s", 1800))
        self.max_turns: int | None = config_dict.get("max_turns")
        self.model: str | None = config_dict.get("model")
        self.env_overrides: dict[str, str] = dict(config_dict.get("env") or {})
        # Names of environment variables to remove from the inherited env before
        # spawning the CLI subprocess. Subclasses override the class-level
        # ``default_scrub_env`` to scrub framework-specific vars that confuse
        # the CLI (e.g. ``ANTHROPIC_BASE_URL`` set to a full /v1/messages
        # endpoint by litellm-style configs).
        scrub_from_config: list[str] = list(config_dict.get("scrub_env") or [])
        self.scrub_env: list[str] = list(self.default_scrub_env) + scrub_from_config

        self.instruction: str | None = None
        self.logger = logging.getLogger(self.__class__.__name__)

        # Populated after step() runs; orchestrator reads these.
        self.last_telemetry: CLITelemetry | None = None
        self.last_run: CLIRunResult | None = None
        self.last_transcript_path: Path | None = None

        # Required by orchestrator wiring; CLI agents have no ActionSpace.
        self.action_space = None

    # ------------------------------------------------------------------
    # Agent interface
    # ------------------------------------------------------------------
    def set_instruction(self, instruction: str) -> None:
        self.instruction = instruction

    def reset(self) -> None:
        self.instruction = None
        self.last_telemetry = None
        self.last_run = None
        self.last_transcript_path = None

    def close(self) -> None:
        pass

    def step(self, state: State) -> Action:
        if not isinstance(state, WorkspaceState):
            raise ValueError(
                f"{self.__class__.__name__} requires WorkspaceState, got {type(state)}"
            )
        if self.instruction is None:
            raise ValueError("Instruction not set. Call set_instruction() first.")

        # Preflight: CLI binary must be on PATH.
        if shutil.which(self.binary) is None:
            raise RuntimeError(
                f"CLI binary '{self.binary}' not found on PATH. Install it and "
                f"ensure `{self.binary} --version` works, then re-run."
            )

        prompt = self._build_prompt(state)
        cmd = self._build_command(prompt=prompt, workspace_dir=state.workspace_dir)
        transcript_path = state.workspace_dir.parent / f"{self.cli_name}_transcript.ndjson"
        stdout_path = state.workspace_dir.parent / f"{self.cli_name}_stdout.log"
        stderr_path = state.workspace_dir.parent / f"{self.cli_name}_stderr.log"

        run = self._invoke(
            cmd=cmd,
            cwd=state.workspace_dir,
            stdin_text=self._stdin_text(prompt),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            transcript_path=transcript_path,
        )
        self.last_run = run
        self.last_transcript_path = run.transcript_path

        try:
            telemetry = self._parse_telemetry(run)
        except Exception as parse_err:  # noqa: BLE001
            self.logger.warning(
                f"[{self.cli_name}] telemetry parsing failed: {parse_err}"
            )
            telemetry = CLITelemetry(
                duration_seconds=run.duration_seconds,
                cli_exit_code=run.exit_code,
                cli_error=f"telemetry_parse_error: {parse_err}",
                model=self.model,
            )

        telemetry.duration_seconds = run.duration_seconds
        telemetry.cli_exit_code = run.exit_code
        if telemetry.model is None:
            telemetry.model = self.model
        if run.exit_code != 0 and telemetry.cli_error is None:
            tail = (run.stderr or run.stdout or "").strip().splitlines()[-5:]
            telemetry.cli_error = (
                f"non-zero exit code {run.exit_code}; tail: " + " | ".join(tail)
            )
        if run.timed_out and telemetry.cli_error is None:
            telemetry.cli_error = f"timeout after {self.timeout_s}s"

        self.last_telemetry = telemetry

        # Write the canonical telemetry file next to other per-task outputs.
        try:
            (state.workspace_dir.parent / "cli_telemetry.json").write_text(
                json.dumps(telemetry.to_dict(), indent=2),
                encoding="utf-8",
            )
        except OSError as write_err:
            self.logger.warning(f"Failed to write cli_telemetry.json: {write_err}")

        return Action(
            action_type="cli_run",
            params={
                "cli_name": self.cli_name,
                "binary": self.binary,
                "exit_code": run.exit_code,
                "duration_seconds": run.duration_seconds,
                "transcript_path": str(run.transcript_path) if run.transcript_path else None,
                "telemetry": telemetry.to_dict(),
            },
            reasoning=f"Invoked {self.cli_name} once; CLI ran its own internal loop.",
        )

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------
    def _build_prompt(self, state: WorkspaceState) -> str:
        """Default prompt: instruct the CLI to read TASK.md + OUTPUT_INSTRUCTIONS.md."""
        return (
            "You are running inside a per-task workspace. Read TASK.md and "
            "OUTPUT_INSTRUCTIONS.md in the current directory, then complete "
            "the task by writing the result to the path specified in "
            "OUTPUT_INSTRUCTIONS.md. Do not deviate from the output path. "
            "When the output file exists and matches the task requirements, "
            "exit."
        )

    def _build_command(self, prompt: str, workspace_dir: Path) -> list[str]:
        raise NotImplementedError

    def _stdin_text(self, prompt: str) -> str | None:
        """Return text to pipe via stdin, or None to omit stdin."""
        return None

    def _parse_telemetry(self, run: CLIRunResult) -> CLITelemetry:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Process invocation
    # ------------------------------------------------------------------
    def _invoke(
        self,
        cmd: list[str],
        cwd: Path,
        stdin_text: str | None,
        stdout_path: Path,
        stderr_path: Path,
        transcript_path: Path,
    ) -> CLIRunResult:
        env = os.environ.copy()
        for name in self.scrub_env:
            env.pop(name, None)
        env.update(self.env_overrides)

        self.logger.info(f"[{self.cli_name}] cwd={cwd}")
        self.logger.info(f"[{self.cli_name}] cmd={cmd}")

        t0 = time.time()
        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                input=stdin_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_s,
                env=env,
                check=False,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            exit_code = int(proc.returncode)
        except subprocess.TimeoutExpired as e:
            timed_out = True
            stdout = (e.stdout.decode("utf-8", errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) or ""
            stderr = (e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")) or ""
            exit_code = -1
        duration = time.time() - t0

        try:
            stdout_path.write_text(stdout, encoding="utf-8")
            stderr_path.write_text(stderr, encoding="utf-8")
        except OSError:
            pass

        # Persist whatever the CLI streamed as the canonical transcript. For
        # JSON-streaming CLIs the stdout IS the transcript.
        try:
            transcript_path.write_text(stdout, encoding="utf-8")
            transcript_out: Path | None = transcript_path
        except OSError:
            transcript_out = None

        return CLIRunResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            transcript_path=transcript_out,
            timed_out=timed_out,
        )
