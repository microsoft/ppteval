#!/usr/bin/env python3
"""
PPTEval Benchmark Runner

Simple entry script for running benchmarks. Just handles:
- Argument parsing
- Agent config loading
- Task filtering
- Concurrent execution
- Incremental result saving

All execution, logging, and grading is delegated to Orchestrator.

Usage:
    python -m ppteval.run_benchmark --agent-config ppteval/configs/claude-4-sonnet.yaml --concurrent 4
    python -m ppteval.run_benchmark --agent-config ppteval/configs/uitars70b.yaml --task-ids "3-002,3-003"
    python -m ppteval.run_benchmark --verify-only --results-dir results/run_1
"""

import argparse
import concurrent.futures
import json
import logging
import os
import shutil
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Load .env first
load_dotenv(verbose=False, override=True)

from ppteval import (
    CUAAgent,
    GPT5xAgent,
    ClaudeAgent,
    UITARSAgent,
    UITARSVLLMAgent,
    Qwen3VLAgent,
    OpenCUAAgent,
    ClaudeCodeAgent,
    CopilotCLIAgent,
    CodexCLIAgent,
    CLIWorkspaceEnvironment,
    Orchestrator,
    TaskRegistry,
    EnvironmentConfig,
    OrchestratorConfig,
)
from ppteval.config import (
    CUAConfig,
    GPT5xConfig,
    ClaudeConfig,
    UITARSConfig,
    UITARSVLLMConfig,
    Qwen3VLConfig,
    OpenCUAConfig,
    CLIAgentConfig,
)

# No locks needed - each concurrent shard writes to its own file.


AGENT_TYPES = {
    "cua": (CUAConfig, CUAAgent),
    "gpt5x": (GPT5xConfig, GPT5xAgent),
    "uitars": (UITARSConfig, UITARSAgent),
    "uitars-vllm": (UITARSVLLMConfig, UITARSVLLMAgent),
    "claude": (ClaudeConfig, ClaudeAgent),
    "qwen3vl": (Qwen3VLConfig, Qwen3VLAgent),
    "opencua": (OpenCUAConfig, OpenCUAAgent),
    "cli": (CLIAgentConfig, None),  # agent class is selected by cli_name
}

# Subclasses selected by ``cli_name`` for the "cli" agent_type.
CLI_AGENT_CLASSES = {
    "claude-code": ClaudeCodeAgent,
    "copilot-cli": CopilotCLIAgent,
    "codex-cli": CodexCLIAgent,
}


def get_agent_type_from_config(agent_config_path: str | Path) -> str:
    """Read the agent family from an agent config YAML."""
    with open(agent_config_path, 'r') as f:
        data = yaml.safe_load(f) or {}

    agent_type = data.get("agent_type")
    if not agent_type:
        raise ValueError(f"Agent config {agent_config_path} must include an agent_type field.")
    if agent_type not in AGENT_TYPES:
        supported = ", ".join(sorted(AGENT_TYPES))
        raise ValueError(f"Unsupported agent_type '{agent_type}'. Supported agent types: {supported}")
    return str(agent_type)


def create_agent_config(agent_config_path: str | Path):
    """Create the agent config that is the source of truth for model and display settings."""
    agent_type = get_agent_type_from_config(agent_config_path)
    config_class, _ = AGENT_TYPES[agent_type]
    return config_class.from_yaml(agent_config_path)


def get_agent_display_resolution(agent_config_path: str | Path) -> tuple[int, int]:
    """Return the sandbox resolution dictated by the selected agent config."""
    agent_config = create_agent_config(agent_config_path)
    return int(agent_config.display_size.width), int(agent_config.display_size.height)


def create_agent(agent_config_path: str | Path):
    """Create agent from a config-defined agent type and model settings."""
    agent_config = create_agent_config(agent_config_path)
    if agent_config.agent_type == "cli":
        cli_name = getattr(agent_config, "cli_name", None)
        agent_cls = CLI_AGENT_CLASSES.get(str(cli_name))
        if agent_cls is None:
            supported = ", ".join(sorted(CLI_AGENT_CLASSES))
            raise ValueError(
                f"Unknown cli_name '{cli_name}'. Supported: {supported}"
            )
        return agent_cls(config=agent_config)
    _, agent_class = AGENT_TYPES[agent_config.agent_type]
    return agent_class(config=agent_config)


def is_cli_agent_config(agent_config_path: str | Path) -> bool:
    """Return True when the YAML at ``agent_config_path`` is a CLI agent."""
    return get_agent_type_from_config(agent_config_path) == "cli"


def setup_logging(results_dir: Path) -> logging.Logger:
    """Setup main benchmark logger."""
    log_file = results_dir / "benchmark.log"
    logger = logging.getLogger("benchmark")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []

    # File handler
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    logger.addHandler(ch)

    return logger


def _read_result_file(result_file: Path) -> dict | None:
    """Read a task result file, returning None for malformed files."""
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _iter_task_result_files(results_dir: Path):
    """Yield task result files from direct and sharded result directories."""
    if not results_dir.exists():
        return

    search_roots = [results_dir]
    search_roots.extend(
        shard_dir for shard_dir in sorted(results_dir.glob("shard_*")) if shard_dir.is_dir()
    )

    seen: set[Path] = set()
    for root in search_roots:
        for result_file in root.glob("*/result_evaluate.json"):
            if result_file not in seen:
                seen.add(result_file)
                yield result_file


def _iter_worker_result_files(results_dir: Path):
    """Yield JSONL worker result files from direct and sharded result directories."""
    if not results_dir.exists():
        return

    roots = [results_dir]
    roots.extend(shard_dir for shard_dir in sorted(results_dir.glob("shard_*")) if shard_dir.is_dir())

    collected: dict[Path, float] = {}
    for root in roots:
        for worker_file in root.glob("results_worker_*.jsonl"):
            if worker_file not in collected:
                try:
                    collected[worker_file] = worker_file.stat().st_mtime
                except OSError:
                    collected[worker_file] = 0.0

    for worker_file, _ in sorted(collected.items(), key=lambda item: item[1]):
        yield worker_file


def load_previous_results(results_dir: Path) -> dict:
    """Load previous results from summary, shard worker files, and task result files."""
    previous_results: dict[str, dict] = {}

    summary = results_dir / "benchmark_summary.json"
    if summary.exists():
        with open(summary, 'r', encoding='utf-8') as f:
            data = json.load(f)
            previous_results.update({
                r["task_id"]: r for r in data.get("task_results", []) if "task_id" in r
            })

    for worker_file in _iter_worker_result_files(results_dir):
        with open(worker_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    result = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "task_id" in result:
                    previous_results[result["task_id"]] = result

    for result_file in _iter_task_result_files(results_dir):
        result = _read_result_file(result_file)
        if result and "task_id" in result:
            previous_results[result["task_id"]] = result

    return previous_results


def should_retry(task_id: str, prev_results: dict) -> bool:
    """Check if task should be retried.

    Retries cover two situations:
    * Generic infrastructure failures (full re-execution).
    * Verification-only screenshot failures (re-grade without re-executing
      the agent; handled by ``run_single_task``).
    """
    if task_id not in prev_results:
        return True
    status = prev_results[task_id].get("execution_status")
    return status in ("infrastructure_failure", "verification_screenshot_unavailable")


def get_completed_tasks(results_dir: Path) -> set:
    """Get set of task IDs that have successfully completed execution.

    A task is considered completed if:
    - result_evaluate.json exists
    - execution_status is 'success' (task ran without infrastructure failures)
    - Has a score (verification ran, even if it failed)

    This allows re-running tasks that failed due to infrastructure issues,
    but skips tasks where execution succeeded (even if the agent failed the task).
    """
    completed = set()

    for result_file in _iter_task_result_files(results_dir):
        data = _read_result_file(result_file)
        if not data:
            continue

        # Only skip if execution completed successfully
        # (even if agent failed the task or verification had issues)
        execution_status = data.get("execution_status", "")
        score = data.get("score")

        if execution_status == "success" and score is not None:
            task_id = data.get("task_id") or result_file.parent.name
            completed.add(task_id)

    return completed


def save_task_result(results_dir: Path, result: dict, worker_id: int = 0):
    """Save individual task result to worker-specific file."""
    worker_file = results_dir / f"results_worker_{worker_id}.jsonl"

    # Append to JSONL file (one JSON object per line)
    with open(worker_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(result) + '\n')


# ---------------------------------------------------------------------------
# --resume classification
# ---------------------------------------------------------------------------
# Verification reached a terminal verdict (regardless of whether the output
# matched the rubric). Re-running these wastes compute — the agent's output
# is on disk and the grader already scored it.
_RESUME_TERMINAL_VERIF = {"success", "failed", "re-verified"}

# Verification failed for infrastructure reasons (grader crash, screenshots
# unavailable, OneDrive download failure, etc.). The agent's pptx is still on
# disk so re-grading is sufficient.
_RESUME_INFRA_VERIF = {
    "error",
    "screenshot_unavailable",
    "grading_failed",
    "no_artifacts_found",
    "no_result_file",
    "",
}

# Execution that ended in a state where the harness itself crashed mid-run.
# No usable artifacts → must re-execute the agent end-to-end.
_RESUME_INTERRUPTED_EXEC = {"agent_error", "infrastructure_failure"}

# Agent legitimately gave up (step ceiling, time limit). Output is on disk
# (possibly partial) and was graded — don't waste compute re-running.
_RESUME_LEGIT_AGENT_FAIL = {"max_steps"}


def _resume_has_orphaned_artifacts(results_dir: Path, task_id: str) -> bool:
    """Per-task dir contains an output pptx but no terminal result file.

    Signals "agent executed and produced output, but the grading step was
    interrupted before any ``result*.json`` was written." Recoverable by
    re-verification only.
    """
    roots = [results_dir, *sorted(results_dir.glob("shard_*"))]
    for root in roots:
        if not root.is_dir():
            continue
        candidates = list(root.glob(task_id)) + list(root.glob(f"{task_id}_*"))
        for cand in candidates:
            if not cand.is_dir():
                continue
            has_result = (cand / "result.json").exists() or (cand / "result_evaluate.json").exists()
            if has_result:
                continue
            # GUI agent: downloaded pptx lands directly in the task dir.
            if any(cand.glob("*.pptx")):
                return True
            # CLI agent: agent writes to workspace/output/<task_id>.<ext>.
            out_dir = cand / "workspace" / "output"
            if out_dir.is_dir() and any(out_dir.iterdir()):
                return True
    return False


def classify_task_for_resume(task_id: str, prev_results: dict, results_dir: Path) -> str:
    """Decide what --resume should do with this task.

    Returns one of:
      * ``"skip"``    — terminal state, don't waste compute
      * ``"reverify"`` — re-run grader only (agent output is on disk)
      * ``"rerun"``   — re-execute agent end-to-end + re-grade

    Decision matrix:
      | exec_status                            | verif_status / state      | action   |
      | -------------------------------------- | ------------------------- | -------- |
      | (no prior entry, no orphaned pptx)     | —                         | rerun    |
      | (no prior entry, orphaned pptx exists) | —                         | reverify |
      | success                                | success/failed/re-verified| skip     |
      | success                                | infra/missing             | reverify |
      | verification_screenshot_unavailable    | any                       | reverify |
      | max_steps                              | any                       | skip     |
      | agent_error / infrastructure_failure   | any                       | rerun    |
      | error (no artifacts/result_file)       | —                         | rerun    |
      | unknown / missing                      | —                         | rerun    |
    """
    prev = prev_results.get(task_id)
    if prev is None:
        return "reverify" if _resume_has_orphaned_artifacts(results_dir, task_id) else "rerun"

    exec_status = (prev.get("execution_status") or "").strip()
    verif_status = (prev.get("verification_status") or "").strip()
    score = prev.get("score")

    if exec_status in _RESUME_LEGIT_AGENT_FAIL:
        return "skip"

    if exec_status in _RESUME_INTERRUPTED_EXEC:
        return "rerun"

    if exec_status == "verification_screenshot_unavailable":
        return "reverify"

    if exec_status == "success":
        if verif_status in _RESUME_TERMINAL_VERIF and score is not None:
            return "skip"
        if verif_status in _RESUME_INFRA_VERIF:
            return "reverify"
        # Unknown verif_status with successful exec — safest is re-verify.
        return "reverify"

    if exec_status == "error":
        return "rerun"

    return "rerun"


def combine_worker_results(results_dir: Path, start_time: float) -> dict:
    """Combine worker result files from direct and sharded runs into final summary."""
    results_by_task: dict[str, dict] = {}

    # Read worker files first; task result files can fill gaps if a run was interrupted.
    for worker_file in _iter_worker_result_files(results_dir):
        with open(worker_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                result = json.loads(line)
                if "task_id" in result:
                    results_by_task[result["task_id"]] = result

    for result_file in _iter_task_result_files(results_dir):
        result = _read_result_file(result_file)
        if result and "task_id" in result:
            results_by_task.setdefault(result["task_id"], result)

    all_results = sorted(results_by_task.values(), key=lambda result: result.get("task_id", ""))

    # Calculate stats
    total = len(all_results)
    successful = sum(1 for r in all_results if r.get("success"))
    total_time = time.time() - start_time if start_time else 0

    # CLI telemetry aggregation (None-safe — non-CLI runs simply contribute 0).
    def _sum(field_name: str) -> float:
        return sum((r.get(field_name) or 0) for r in all_results)

    strict_pass = sum(
        1 for r in all_results if (r.get("score") or 0) >= 1.0
    )

    summary = {
        "benchmark_info": {
            "start_time": datetime.fromtimestamp(start_time).isoformat() if start_time else None,
            "end_time": datetime.now().isoformat(),
            "total_duration_seconds": total_time,
            "total_duration_hours": total_time / 3600,
        },
        "overall_stats": {
            "total_tasks": total,
            "successful_tasks": successful,
            "failed_tasks": total - successful,
            "success_rate": successful / total if total > 0 else 0,
            "pass_rate_strict": strict_pass / total if total > 0 else 0,
            "avg_score": sum((r.get("score") or 0) for r in all_results) / total if total > 0 else 0,
            "avg_steps": sum((r.get("agent_steps") or 0) for r in all_results) / total if total > 0 else 0,
            "total_cost_usd": _sum("cost_usd"),
            "total_tokens": _sum("total_tokens"),
            "total_tool_calls": _sum("num_tool_calls"),
            "total_turns": _sum("agent_turns"),
        },
        "task_results": all_results,
    }

    # Save final summary
    summary_path = results_dir / "benchmark_summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)

    return summary


def _prior_execution_status(results_dir: Path, task_id: str) -> str | None:
    """Return the most-recently-recorded execution_status for a task, if any."""
    candidates = []
    for shard_dir in [results_dir, *sorted(results_dir.glob("shard_*"))]:
        if not shard_dir.is_dir():
            continue
        for sub in [shard_dir / task_id, *shard_dir.glob(f"{task_id}_*")]:
            for name in ("result_evaluate.json", "result.json"):
                f = sub / name
                if f.exists():
                    candidates.append(f)
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    try:
        with open(latest, "r", encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("execution_status")
    except Exception:
        return None


def run_single_task(task, agent_config_path, env_config, orch_config, verify_only, worker_id=0):
    """Run or verify a single task (orchestrator does all the work)."""
    print(f"[{task.task_id}] Starting...")

    # Auto-promote to verify-only retry when a prior run flagged screenshot
    # rendering as unavailable. The agent output is already on disk; we only
    # need to re-run the grader.
    if not verify_only:
        prior = _prior_execution_status(orch_config.results_dir, task.task_id)
        if prior == "verification_screenshot_unavailable":
            print(
                f"[{task.task_id}] Prior run flagged screenshots unavailable; "
                f"switching to verify-only retry (no agent re-execution)."
            )
            verify_only = True

    try:
        if verify_only:
            # Verification mode - orchestrator handles it
            orchestrator = Orchestrator(
                config=orch_config,
                environment=None,  # Not needed for verification
                agent=None,  # Not needed for verification
            )
            task_result = orchestrator.verify_task(task)
        else:
            # Full execution
            agent = create_agent(agent_config_path)
            if is_cli_agent_config(agent_config_path):
                environment = CLIWorkspaceEnvironment(
                    task=task,
                    config=env_config,
                    customization_dir=getattr(env_config, "cli_customization_dir", None),
                )
            else:
                from ppteval.environments import ScreenEnvEnvironment
                environment = ScreenEnvEnvironment(
                    task=task,
                    config=env_config,
                    client_id=os.getenv("CLIENT_ID"),
                )
            orchestrator = Orchestrator(
                config=orch_config,
                environment=environment,
                agent=agent,
            )
            task_result = orchestrator.run_task(task)

            # Cleanup
            environment.close()
            agent.close()

        # Convert to dict
        result = {
            "task_id": task.task_id,
            "goal": task.goal,
            "success": task_result.success,
            "score": task_result.score if task_result.score is not None else 0.0,
            "agent_steps": task_result.agent_steps,
            "execution_time_seconds": task_result.execution_time_seconds,
            "execution_status": task_result.execution_status,
            "verification_status": task_result.verification_status,
            "error_message": task_result.error_message,
        }

        # CLI telemetry (None for non-CLI agents).
        if task_result.cli_telemetry is not None:
            result["cli_telemetry"] = task_result.cli_telemetry
        for field_name in ("agent_turns", "num_tool_calls", "total_tokens", "cost_usd"):
            value = getattr(task_result, field_name, None)
            if value is not None:
                result[field_name] = value

        status = "[PASS]" if result["success"] else "[FAIL]"
        print(f"[{task.task_id}] {status} Score: {result['score']:.2f}")

        # Print reason from evaluation if available
        if task_result.evaluation_result and task_result.evaluation_result.reason:
            reason_preview = task_result.evaluation_result.reason[:200]
            print(f"  Reason: {reason_preview}...")

        # Print error message if failed
        if not result["success"] and result.get("error_message"):
            print(f"  Error: {result['error_message'][:200]}")

        # Save to worker-specific file
        save_task_result(orch_config.results_dir, result, worker_id)
        return result

    except Exception as e:
        print(f"[{task.task_id}] [ERROR] {str(e)[:200]}")

        result = {
            "task_id": task.task_id,
            "goal": task.goal,
            "success": False,
            "score": 0.0,
            "execution_status": "error",
            "error_message": str(e),
        }
        save_task_result(orch_config.results_dir, result, worker_id)
        return result


def partition_tasks(tasks: list, shard_count: int) -> list[list]:
    """Partition tasks into stable round-robin shards."""
    shards = [[] for _ in range(shard_count)]
    for index, task in enumerate(tasks):
        shards[index % shard_count].append(task)
    return shards


def run_task_shard(
    shard_index: int,
    shard_tasks: list,
    agent_config_path,
    env_config,
    orch_config,
    verify_only: bool,
) -> list[dict]:
    """Run one shard serially in its own result directory."""
    shard_dir = orch_config.results_dir / f"shard_{shard_index}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_orch_config = replace(orch_config, results_dir=shard_dir)

    results = []
    for task in shard_tasks:
        results.append(
            run_single_task(
                task,
                agent_config_path,
                env_config,
                shard_orch_config,
                verify_only,
                worker_id=shard_index,
            )
        )
    return results


def main():
    parser = argparse.ArgumentParser(description="PPTEval Benchmark Runner")

    # Modes
    parser.add_argument("--verify-only", action="store_true", help="Re-verify existing results")
    parser.add_argument("--retry-infrastructure", action="store_true", help="Retry infrastructure failures only")
    parser.add_argument("--skip-completed", action="store_true", help="Skip tasks that already have results")
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Smart resume: per-task, re-execute interrupted/infra-failed tasks, "
            "re-grade tasks where validation errored, and skip tasks that "
            "completed cleanly (incl. legitimate agent failures like max_steps). "
            "Requires --results-dir pointing at an existing run."
        ),
    )

    # Agent
    parser.add_argument("--agent-config", help="Agent config YAML file")

    # Tasks
    parser.add_argument("--task-registry", default="task_registry", help="Task registry path")
    parser.add_argument("--task-ids", help="Comma-separated task IDs")

    # Execution
    parser.add_argument("--results-dir", help="Results directory (defaults to timestamped dir)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing results directory")
    parser.add_argument("--concurrent", type=int, default=1, help="Concurrent task shards")
    parser.add_argument("--max-steps", type=int, default=30, help="Maximum steps per task")
    parser.add_argument("--timeout-minutes", type=int, default=30)
    parser.add_argument("--step-delay", type=float, default=1.0)
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--onedrive-root", default="/PPTEval")

    # Grader concern, not an agent concern: how the verifier renders pptx
    # → slide screenshots for VLM-based rubric scoring. Independent of which
    # agent produced the pptx. If omitted, the runner auto-selects: COM for
    # verify-only runs and CLI/code-agent runs (they don't touch OneDrive),
    # otherwise the grader's own default ("online").
    parser.add_argument(
        "--conversion-mode",
        choices=["online", "com", "libreoffice+poppler", "libreoffice+ghostscript"],
        default=None,
        help="Override slide-screenshot rendering mode used by the grader.",
    )

    args = parser.parse_args()

    # Validate
    if not args.verify_only and not args.agent_config:
        parser.error("--agent-config required unless --verify-only")
    # CLI agents don't talk to OneDrive — skip the CLIENT_ID requirement.
    _is_cli_run = (
        not args.verify_only
        and args.agent_config
        and is_cli_agent_config(args.agent_config)
    )
    if not args.verify_only and not _is_cli_run and not os.getenv("CLIENT_ID"):
        print("ERROR: CLIENT_ID not set")
        sys.exit(1)

    # Check for conflicting flags
    if args.overwrite and args.skip_completed:
        print("ERROR: Cannot use both --overwrite and --skip-completed")
        print("  --overwrite: Delete entire results directory and start fresh")
        print("  --skip-completed: Resume existing run by skipping completed tasks")
        print("These options are mutually exclusive.")
        sys.exit(1)

    if args.resume:
        conflicting = [
            name
            for name, val in (
                ("--overwrite", args.overwrite),
                ("--skip-completed", args.skip_completed),
                ("--verify-only", args.verify_only),
                ("--retry-infrastructure", args.retry_infrastructure),
            )
            if val
        ]
        if conflicting:
            print(
                f"ERROR: --resume is mutually exclusive with {', '.join(conflicting)}. "
                f"--resume already decides per task whether to re-execute, re-verify, or skip."
            )
            sys.exit(1)
        if not args.results_dir:
            print("ERROR: --resume requires --results-dir pointing at an existing run.")
            sys.exit(1)
        if not Path(args.results_dir).exists():
            print(f"ERROR: --resume target does not exist: {args.results_dir}")
            sys.exit(1)

    # Setup results directory
    if args.results_dir:
        # User provided custom directory
        results_dir = Path(args.results_dir)
        if results_dir.exists():
            if args.overwrite:
                shutil.rmtree(results_dir)
            elif not (args.skip_completed or args.retry_infrastructure or args.verify_only or args.resume):
                print(f"ERROR: Results directory already exists: {results_dir}")
                print("Use --overwrite, --skip-completed, --retry-infrastructure, --verify-only, --resume, or choose a different directory")
                sys.exit(1)
    else:
        # Auto-generate timestamped directory
        run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        results_dir = Path("evaluation_results") / run_id

    results_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(results_dir)

    logger.info("="*80)
    logger.info("PPTEval Benchmark Runner")
    if args.resume:
        mode_label = "RESUME"
    elif args.verify_only:
        mode_label = "VERIFY-ONLY"
    elif args.retry_infrastructure:
        mode_label = "RETRY"
    else:
        mode_label = "FULL"
    logger.info(f"Mode: {mode_label}")
    logger.info(f"Results: {results_dir}")
    if not args.verify_only:
        logger.info(f"Agent config: {args.agent_config}")
        logger.info(f"Concurrent: {args.concurrent}")
    logger.info("="*80)

    # Load tasks using TaskRegistry
    registry = TaskRegistry(Path(args.task_registry))

    # Filter by task IDs if specified
    if args.task_ids:
        task_ids = [tid.strip() for tid in args.task_ids.split(",")]
        task_dict = registry.filter_by_ids(task_ids)
    else:
        task_dict = registry.load()

    tasks = list(task_dict.values())

    # --resume partitions tasks into two buckets: reverify (grader only) and
    # rerun (agent end-to-end + grader). Tasks that already completed cleanly
    # (or legitimately gave up via max_steps) are dropped. Everything else
    # flows through one or the other pass.
    resume_reverify_tasks: list = []
    resume_rerun_tasks: list = []
    if args.resume:
        prev_results = load_previous_results(results_dir)
        skipped: list[str] = []
        for t in tasks:
            action = classify_task_for_resume(t.task_id, prev_results, results_dir)
            if action == "skip":
                skipped.append(t.task_id)
            elif action == "reverify":
                resume_reverify_tasks.append(t)
            else:
                resume_rerun_tasks.append(t)
        logger.info(
            f"Resume plan: {len(resume_rerun_tasks)} rerun, "
            f"{len(resume_reverify_tasks)} reverify, "
            f"{len(skipped)} skip (of {len(tasks)} requested)"
        )
        if skipped:
            preview = ", ".join(skipped[:10]) + (f", +{len(skipped) - 10} more" if len(skipped) > 10 else "")
            logger.info(f"  Skipped: {preview}")
        # The downstream code expects `tasks` to be everything we'll touch
        # (used for conversion_mode wiring etc.); set it to the union.
        tasks = resume_reverify_tasks + resume_rerun_tasks

    # Filter for retry mode
    if args.retry_infrastructure:
        prev_results = load_previous_results(results_dir)
        tasks = [t for t in tasks if should_retry(t.task_id, prev_results)]
        logger.info(f"Retrying {len(tasks)} infrastructure failures")

    # Filter for skip-completed mode
    if args.skip_completed:
        completed_tasks = get_completed_tasks(results_dir)
        original_count = len(tasks)
        tasks = [t for t in tasks if t.task_id not in completed_tasks]
        skipped_count = original_count - len(tasks)
        logger.info(f"Skipping {skipped_count} already completed tasks")
        logger.info(f"Remaining tasks to process: {len(tasks)}")

    if not tasks:
        logger.error("No tasks to run")
        return

    logger.info(f"Processing {len(tasks)} tasks")

    # Resolve grader rendering mode. Force COM for verify-only and CLI/code
    # agent runs (no OneDrive/Playwright path); otherwise honor explicit
    # --conversion-mode, else leave grader default ("online").
    if args.conversion_mode is not None:
        resolved_conversion_mode = args.conversion_mode
    elif args.verify_only or _is_cli_run:
        resolved_conversion_mode = "com"
    else:
        resolved_conversion_mode = None
    if resolved_conversion_mode is not None:
        for _t in tasks:
            grader = getattr(_t, "grader", None)
            if grader is not None and hasattr(grader, "conversion_mode"):
                grader.conversion_mode = resolved_conversion_mode
        logger.info(f"Grader conversion_mode = '{resolved_conversion_mode}'")
    else:
        logger.info("Grader conversion_mode = grader default ('online')")

    # Create configs
    if not args.verify_only:
        if _is_cli_run:
            # CLI agents: no GUI/onedrive plumbing; no per-step loop. We still
            # build an EnvironmentConfig stub for API parity with run_single_task.
            env_config = EnvironmentConfig(
                resolution=(1024, 768),
                headless=True,
                step_delay=args.step_delay,
                onedrive_root=args.onedrive_root,
            )
            # Pull CLI-specific extras (customization dir) out of the agent YAML.
            cli_cfg = CLIAgentConfig.from_yaml(args.agent_config)
            cli_customization_dir = cli_cfg.customization_dir
            if cli_customization_dir:
                logger.info(f"CLI customization_dir: {cli_customization_dir}")
            # Stash on env_config so the per-task worker can forward it to
            # CLIWorkspaceEnvironment without changing the worker signature.
            env_config.cli_customization_dir = cli_customization_dir  # type: ignore[attr-defined]

            orch_config = OrchestratorConfig(
                results_dir=results_dir,
                max_steps=1,            # CLI agents run their own internal loop
                timeout_minutes=args.timeout_minutes,
                enable_logging=True,
                save_screenshots=False,
                screenshot_interval=1,
            )
        else:
            cli_customization_dir = None
            w, h = get_agent_display_resolution(args.agent_config)
            env_config = EnvironmentConfig(
                resolution=(w, h),
                headless=not args.no_headless,
                step_delay=args.step_delay,
                onedrive_root=args.onedrive_root,
            )
            orch_config = OrchestratorConfig(
                results_dir=results_dir,
                max_steps=args.max_steps,
                timeout_minutes=args.timeout_minutes,
                enable_logging=True,
                save_screenshots=True,
                screenshot_interval=1,
            )
            logger.info(f"Max steps configured: {args.max_steps}")
            logger.info(f"Resolution configured from agent config: {w}x{h}")
    else:
        env_config = None
        orch_config = OrchestratorConfig(results_dir=results_dir)

    # Run tasks
    start_time = time.time()

    def _dispatch(tasks_to_run, *, verify_only: bool, pass_label: str):
        """Run a batch of tasks sharded (if concurrent>1) or sequentially."""
        if not tasks_to_run:
            return []
        shard_count_local = max(1, min(args.concurrent, len(tasks_to_run)))
        if shard_count_local > 1:
            logger.info(
                f"[{pass_label}] Running {len(tasks_to_run)} tasks across "
                f"{shard_count_local} shards (verify_only={verify_only})"
            )
            shards = partition_tasks(tasks_to_run, shard_count_local)
            with concurrent.futures.ThreadPoolExecutor(max_workers=shard_count_local) as executor:
                futures = [
                    executor.submit(
                        run_task_shard,
                        shard_index,
                        shard_tasks,
                        args.agent_config,
                        env_config,
                        orch_config,
                        verify_only,
                    )
                    for shard_index, shard_tasks in enumerate(shards)
                    if shard_tasks
                ]
                return [
                    result
                    for future in concurrent.futures.as_completed(futures)
                    for result in future.result()
                ]
        logger.info(
            f"[{pass_label}] Running {len(tasks_to_run)} tasks sequentially "
            f"(verify_only={verify_only})"
        )
        out = []
        for i, task in enumerate(tasks_to_run, 1):
            logger.info(f"\n[{pass_label} {i}/{len(tasks_to_run)}] {task.task_id}")
            out.append(
                run_single_task(
                    task, args.agent_config, env_config, orch_config, verify_only, worker_id=0
                )
            )
        return out

    if args.resume:
        # Pass 1: re-verify (cheap, no agent execution). Pass 2: full rerun.
        results = []
        results.extend(_dispatch(resume_reverify_tasks, verify_only=True, pass_label="resume.reverify"))
        results.extend(_dispatch(resume_rerun_tasks, verify_only=False, pass_label="resume.rerun"))
    else:
        results = _dispatch(tasks, verify_only=args.verify_only, pass_label=mode_label.lower())

    # Combine all worker results into final summary
    logger.info("\nCombining results...")
    summary = combine_worker_results(results_dir, start_time)
    stats = summary["overall_stats"]

    logger.info("\n" + "="*80)
    logger.info("FINAL RESULTS")
    logger.info(f"Total: {stats['total_tasks']}")
    logger.info(f"Success: {stats['successful_tasks']} ({stats['success_rate']*100:.1f}%)")
    logger.info(f"Strict pass (score==1): {stats.get('pass_rate_strict', 0)*100:.1f}%")
    logger.info(f"Avg Score: {stats['avg_score']:.2f}")
    logger.info(f"Avg Steps: {stats['avg_steps']:.1f}")
    if stats.get('total_cost_usd') or stats.get('total_tokens'):
        logger.info(f"Total Cost (USD): {stats.get('total_cost_usd', 0):.4f}")
        logger.info(f"Total Tokens: {int(stats.get('total_tokens', 0))}")
        logger.info(f"Total Tool Calls: {int(stats.get('total_tool_calls', 0))}")
        logger.info(f"Total Turns: {int(stats.get('total_turns', 0))}")
    logger.info("="*80)

    logger.info(f"\nResults saved to: {results_dir}")


if __name__ == "__main__":
    main()
