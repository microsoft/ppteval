"""Batch task proposal script for PowerPoint files."""

import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from ppteval.agents import ClaudeTaskProposer
from ppteval.config import ClaudeConfig, EnvironmentConfig
from ppteval.core.base import EvaluationResult, Grader
from ppteval.core.task import Task
from ppteval.environments import ScreenEnvEnvironment
from ppteval.utils.task_proposal import proposed_tasks


class NoOpGrader(Grader):
    """Placeholder grader; task proposal does not run verification."""

    def evaluate(self, artifacts: dict[str, Path]) -> EvaluationResult:
        return EvaluationResult(score=0.0, success=False, reason="Task proposal does not grade outputs.")


def parse_task_string(task_str: str) -> tuple[str, list[str]]:
    """Extract leading bracketed tags from a proposed task string."""
    tags: list[str] = []
    remaining = task_str

    while True:
        match = re.match(r"^\s*\[(?P<tag>[^\]]+)\]\s*", remaining)
        if not match:
            break
        tags.append(match.group("tag").strip())
        remaining = remaining[match.end():]

    goal = remaining.strip(" \t\r\n:;-")
    return goal, tags


def discover_files(files: list[str], directory: str | None) -> list[Path]:
    """Resolve explicitly provided files and files discovered in a local directory."""
    discovered: list[Path] = []
    if files:
        discovered.extend(Path(file_path) for file_path in files)

    if directory:
        dir_path = Path(directory)
        if dir_path.exists() and dir_path.is_dir():
            for ext in ("*.pptx", "*.ppt"):
                discovered.extend(sorted(dir_path.glob(ext)))
        else:
            print(f"Warning: --dir '{directory}' is not a local directory. Skipping directory discovery.")

    seen: set[Path] = set()
    unique: list[Path] = []
    for file_path in discovered:
        resolved = file_path.expanduser().resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def tasks_to_serializable(file_path: Path, task_strings: list[str]) -> dict:
    """Convert generated task strings into a JSON-serializable payload."""
    serializable_tasks: list[dict] = []
    base_stem = file_path.stem

    for idx, raw in enumerate(task_strings, start=1):
        goal, tags = parse_task_string(raw)
        serializable_tasks.append(
            {
                "task_id": f"{base_stem}-{idx:03d}",
                "goal": goal,
                "tags": tags,
                "file_path": str(file_path),
                "misc": {"tags": tags},
            }
        )

    return {
        "file": str(file_path),
        "num_tasks": len(serializable_tasks),
        "tasks": serializable_tasks,
    }


def run_for_file(
    file_path: Path,
    agent_config_path: Path,
    task_instruction: str,
    max_steps: int,
    headless: bool,
    step_delay: float,
    onedrive_root: str,
) -> list[str]:
    """Open a PowerPoint file in the sandbox and collect task proposals."""
    proposed_tasks.set([])

    agent = ClaudeTaskProposer(config=agent_config_path)
    agent.set_instruction(task_instruction)

    display_size = agent.agent_config.display_size
    env_config = EnvironmentConfig(
        headless=headless,
        resolution=(display_size.width, display_size.height),
        step_delay=step_delay,
        onedrive_root=onedrive_root,
    )
    task = Task(
        task_id=file_path.stem,
        goal=task_instruction,
        input_file_path=file_path,
        grader=NoOpGrader(),
        tags=[],
        metadata={"purpose": "task_proposal"},
    )
    env = ScreenEnvEnvironment(task=task, config=env_config, client_id=os.getenv("CLIENT_ID"))

    try:
        state = env.setup()
        for _ in range(max_steps):
            action = agent.step(state)
            state = env.update(action)
            if state.done:
                break
        return proposed_tasks.get()
    finally:
        env.close()
        agent.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch propose tasks for PowerPoint files")
    parser.add_argument("--files", nargs="*", default=[], help="Specific local PowerPoint files to evaluate")
    parser.add_argument("--dir", default=None, help="Local directory of PowerPoint files to evaluate")
    parser.add_argument("--agent-config", default="ppteval/configs/claude-4-sonnet.yaml", help="Claude agent config YAML")
    parser.add_argument("--output-dir", default="proposed_tasks", help="Directory to write per-file JSON outputs")
    parser.add_argument("--overwrite", action="store_true", help="Recompute outputs even if they already exist")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--max-steps", type=int, default=35, help="Max proposal steps per file")
    parser.add_argument("--step-delay", type=float, default=2.0, help="Delay between actions in seconds")
    parser.add_argument("--onedrive-root", default="/PPTEval")
    args = parser.parse_args()

    load_dotenv(verbose=False, override=True)

    if not os.getenv("CLIENT_ID"):
        raise RuntimeError("CLIENT_ID must be set to run task proposal.")

    agent_config_path = Path(args.agent_config)
    agent_config = ClaudeConfig.from_yaml(agent_config_path)
    if agent_config.agent_type != "claude":
        raise ValueError("Task proposal currently requires a Claude agent config.")

    files_to_run = discover_files(args.files, args.dir)
    if not files_to_run:
        print("No input files provided. Use --files or --dir.")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    task_instruction = (
        "Explore the current PowerPoint file and propose tasks to add to the dataset. "
        "When adding tasks, tag each task as easy, medium, or hard and include a slide number "
        "using the '[DIFFICULTY][SLIDE:N] task' format. Include a variety of realistic tasks "
        "that can be evaluated automatically using python-pptx and/or slide screenshots. "
        "Do not propose tasks requiring personal information, audio, or video validation. "
        "You can add tasks as you explore. When finished, call the finish tool with a reason."
    )

    for file_path in files_to_run:
        print("-" * 60)
        print(f"Evaluating: {file_path}")
        out_path = output_dir / f"{file_path.stem}.proposed_tasks.json"

        if out_path.exists() and not args.overwrite:
            print(f"Skipping {file_path} (output already exists at {out_path}). Use --overwrite to recompute.")
            continue

        try:
            task_strings = run_for_file(
                file_path=file_path,
                agent_config_path=agent_config_path,
                task_instruction=task_instruction,
                max_steps=args.max_steps,
                headless=args.headless,
                step_delay=args.step_delay,
                onedrive_root=args.onedrive_root,
            )
        except Exception as exc:
            print(f"Warning: proposal run failed for '{file_path}': {exc}")
            task_strings = proposed_tasks.get() or []

        payload = tasks_to_serializable(file_path, task_strings)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"Wrote {payload['num_tasks']} tasks to {out_path}")


if __name__ == "__main__":
    main()
