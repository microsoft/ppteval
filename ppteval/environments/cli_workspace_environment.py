"""
CLI-workspace environment for CLI agents (Claude Code, Copilot CLI, Codex CLI).

This environment is filesystem-only — no GUI, no sandbox, no OneDrive. It
prepares a per-task workspace directory seeded with the task's input file(s)
plus deterministic instruction files (TASK.md, OUTPUT_INSTRUCTIONS.md), and
collects the agent's output file after the CLI exits.

The CLI process runs on the host (cwd=workspace_dir) with whatever privileges
the user has. The user is responsible for having the target CLI binary
(``claude``, ``copilot``, ``codex``) installed and on ``PATH``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from ppteval.core.base import Action, Environment, WorkspaceState
from ppteval.core.task import Task


logger = logging.getLogger(__name__)


OUTPUT_INSTRUCTIONS_TEMPLATE = """\
# Output instructions

You are running inside a per-task workspace directory. This file documents
how to produce the result the grader expects.

## Input
The original PowerPoint file is at:

    inputs/{input_filename}

Treat it as read-only. Do not edit it in place — copy it first.

## Output
You MUST produce the modified file at exactly this path:

    output/{output_filename}

The grader will look for this path and nothing else. If the file is missing
or has a different name, the task will be scored 0.

## Scope
Only make the changes required by the task description in `TASK.md`. Do not
restructure unrelated content, do not add commentary slides, do not change
the file name template above.

## When you are done
Exit the agent. Do not leave background processes running.
"""


class CLIWorkspaceEnvironment(Environment):
    """Filesystem workspace environment for CLI agents.

    Per-task layout (created under ``result_dir/workspace/``):

        workspace/
        ├── TASK.md                  # task.goal verbatim
        ├── OUTPUT_INSTRUCTIONS.md   # deterministic I/O contract
        ├── inputs/<orig_filename>   # copied from task.input_file_path
        └── output/                  # agent writes <task_id>.<ext> here

    The Orchestrator sets ``self.result_dir`` before calling ``setup()``.
    """

    def __init__(
        self,
        task: Task,
        config: Any = None,
        copy_inputs: bool = True,
        cleanup_workspace: bool = False,
        customization_dir: str | Path | None = None,
    ):
        self.task = task
        self.config = config
        self.copy_inputs = copy_inputs
        self.cleanup_workspace = cleanup_workspace
        self.customization_dir = Path(customization_dir).resolve() if customization_dir else None

        # Set by orchestrator before setup().
        self.result_dir: Path | None = None
        self.action_space = None  # not used for CLI agents

        # Populated in setup().
        self.workspace_dir: Path | None = None
        self.input_dir: Path | None = None
        self.output_dir: Path | None = None
        self.expected_output: Path | None = None
        self.state: WorkspaceState | None = None

    # ------------------------------------------------------------------
    # Environment interface
    # ------------------------------------------------------------------
    def setup(self) -> WorkspaceState:
        if self.result_dir is None:
            raise RuntimeError(
                "CLIWorkspaceEnvironment.result_dir must be set by the orchestrator "
                "before calling setup()."
            )

        self.workspace_dir = self.result_dir / "workspace"
        self.input_dir = self.workspace_dir / "inputs"
        self.output_dir = self.workspace_dir / "output"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Seed the workspace with user-provided CLI customization (CLAUDE.md,
        # .claude/skills/, AGENTS.md, etc.) BEFORE writing deterministic
        # instruction files so TASK.md/OUTPUT_INSTRUCTIONS.md/inputs always win.
        if self.customization_dir is not None:
            if not self.customization_dir.is_dir():
                logger.warning(
                    f"[CLIWorkspace] customization_dir does not exist or is not a directory: "
                    f"{self.customization_dir} (skipping)"
                )
            else:
                reserved = {"TASK.md", "OUTPUT_INSTRUCTIONS.md", "inputs", "output"}
                for entry in self.customization_dir.iterdir():
                    if entry.name in reserved:
                        logger.warning(
                            f"[CLIWorkspace] customization_dir entry '{entry.name}' "
                            f"conflicts with a reserved workspace path; skipping."
                        )
                        continue
                    dst = self.workspace_dir / entry.name
                    if entry.is_dir():
                        shutil.copytree(entry, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(entry, dst)
                logger.info(
                    f"[CLIWorkspace] Seeded workspace with customization from "
                    f"{self.customization_dir}"
                )

        # Copy (or symlink) the task input file in.
        src = Path(self.task.input_file_path).resolve()
        dst = self.input_dir / src.name
        if self.copy_inputs:
            shutil.copy2(src, dst)
        else:
            try:
                if dst.exists():
                    dst.unlink()
                dst.symlink_to(src)
            except OSError:
                # Symlinks may not be permitted on Windows without dev mode.
                shutil.copy2(src, dst)

        # Compute expected output path.
        ext = src.suffix or ".pptx"
        output_filename = f"{self.task.task_id}{ext}"
        self.expected_output = self.output_dir / output_filename

        # Write deterministic instruction files.
        task_md = self.workspace_dir / "TASK.md"
        task_md.write_text(self._build_task_md(), encoding="utf-8")

        out_md = self.workspace_dir / "OUTPUT_INSTRUCTIONS.md"
        out_md.write_text(
            OUTPUT_INSTRUCTIONS_TEMPLATE.format(
                input_filename=src.name,
                output_filename=output_filename,
            ),
            encoding="utf-8",
        )

        logger.info(f"[CLIWorkspace] Prepared workspace at {self.workspace_dir}")
        logger.info(f"[CLIWorkspace] Expected output: {self.expected_output}")

        self.state = WorkspaceState(
            done=False,
            workspace_dir=self.workspace_dir,
            instruction=self.task.goal,
            input_files=[dst],
            expected_output=self.expected_output,
            cli_result=None,
        )
        return self.state

    def update(self, action: Action) -> WorkspaceState:
        # The only meaningful action is a single ``cli_run`` produced by a
        # CLIAgent. Anything else is a no-op that flips ``done`` to True so
        # the orchestrator loop exits.
        assert self.state is not None
        if action.action_type == "cli_run":
            self.state.cli_result = dict(action.params or {})
        self.state.done = True
        return self.state

    def download_artifacts(self) -> dict[str, Path]:
        artifacts: dict[str, Path] = {
            "original_file": Path(self.task.input_file_path),
        }
        if self.expected_output and self.expected_output.exists():
            artifacts["file"] = self.expected_output
        else:
            logger.warning(
                f"[CLIWorkspace] Expected output not found: {self.expected_output}"
            )
        if self.workspace_dir is not None:
            artifacts["workspace"] = self.workspace_dir
        return artifacts

    def cleanup(self) -> None:
        if self.cleanup_workspace and self.workspace_dir and self.workspace_dir.exists():
            try:
                shutil.rmtree(self.workspace_dir)
            except OSError as e:
                logger.warning(f"[CLIWorkspace] Failed to remove workspace: {e}")

    def close(self) -> None:
        self.cleanup()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_task_md(self) -> str:
        lines = [
            f"# Task: {self.task.task_id}",
            "",
            "## Goal",
            "",
            self.task.goal.strip(),
            "",
            "## I/O contract",
            "",
            "See `OUTPUT_INSTRUCTIONS.md` in this directory for the exact",
            "input and expected output paths. Follow it literally.",
            "",
        ]
        return "\n".join(lines)
