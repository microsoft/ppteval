"""
Orchestrator for coordinating agent evaluation on tasks.

The Orchestrator manages the evaluation loop:
1. Setup environment with task
2. Run agent loop (observe -> act -> update)
3. Collect artifacts and grade results
4. Generate comprehensive logs and results

Handles:
- Max steps and timeout limits
- Centralized logging (actions, timings, screenshots)
- Error handling and recovery
- Per-task JSON result generation
"""

import json
import logging
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# Substrings indicating an upstream model-endpoint / network failure rather than
# a real agent reasoning bug. When we see one of these we treat the step as an
# infrastructure failure so the orchestrator's retry loop kicks in instead of
# burning the whole 30-step budget on a dead endpoint.
_INFRA_ERROR_MARKERS = (
    "NotFoundError",          # 404 from vLLM / OpenAI-compat endpoint
    "RateLimitError",         # 429
    "APIConnectionError",     # socket/TLS/DNS
    "APITimeoutError",        # litellm wrapper
    "ServiceUnavailableError",
    "InternalServerError",    # 500/502/503/504
    "BadGatewayError",
    "GatewayTimeoutError",
    "Connection refused",
    "Connection reset",
    "Connection aborted",
    "Read timed out",
    "Error code: 404",
    "Error code: 429",
    "Error code: 500",
    "Error code: 502",
    "Error code: 503",
    "Error code: 504",
    "infrastructure failure",  # raised by environment layer
)


def _looks_like_infra_error(exc: BaseException) -> bool:
    """Heuristic: did this exception come from the model endpoint / network,
    rather than an agent code path?"""
    msg = f"{type(exc).__name__}: {exc}"
    return any(marker in msg for marker in _INFRA_ERROR_MARKERS)

from ppteval.config import OrchestratorConfig
from ppteval.core.base import (
    Action,
    Agent,
    Environment,
    EvaluationResult,
    Grader,
    State,
    TaskResult,
)
from ppteval.core.task import Task
from ppteval.verify.ppt.verifier import ScreenshotsUnavailableError

logger = logging.getLogger(__name__)


@dataclass
class StepLog:
    """Log entry for a single step"""
    step_number: int
    timestamp: float
    action_type: str
    params: dict[str, Any]
    reasoning: str | None
    duration_ms: float
    screenshot_path: Path | None = None


class Orchestrator:
    """
    Orchestrates agent evaluation on tasks.

    Coordinates Environment, Agent, and Grader to execute tasks and generate results.
    """

    def __init__(
        self,
        config: OrchestratorConfig,
        environment: Environment,
        agent: Agent,
    ):
        """
        Initialize orchestrator.

        Args:
            config: Orchestrator configuration
            environment: Environment instance
            agent: Agent instance
        """
        self.config = config
        self.environment = environment
        self.agent = agent

        # Ensure results directory exists
        self.config.results_dir.mkdir(parents=True, exist_ok=True)

        # Current task tracking
        self.current_task: Task | None = None
        self.current_task_dir: Path | None = None
        self.step_logs: list[StepLog] = []
        self.start_time: float = 0

        logger.info(f"Orchestrator initialized with results_dir={self.config.results_dir}")

    def verify_task(self, task: Task) -> TaskResult:
        """
        Re-verify existing task artifacts without re-running.

        Args:
            task: Task to verify

        Returns:
            TaskResult with new verification results
        """
        logger.info(f"Re-verifying task: {task.task_id}")

        # Find existing task directory in direct and sharded result layouts.
        search_roots = [self.config.results_dir]
        search_roots.extend(
            shard_dir for shard_dir in sorted(self.config.results_dir.glob("shard_*")) if shard_dir.is_dir()
        )
        task_dirs = []
        for root in search_roots:
            task_dirs.append(root / task.task_id)
            task_dirs.extend(root.glob(f"{task.task_id}_*"))
        task_dirs = [task_dir for task_dir in task_dirs if task_dir.exists()]
        if not task_dirs:
            logger.error(f"No existing artifacts found for {task.task_id}")
            return TaskResult(
                task_id=task.task_id,
                goal=task.goal,
                success=False,
                score=None,
                execution_status="error",
                agent_steps=0,
                execution_time_seconds=0.0,
                verification_status="no_artifacts_found",
                error_message="No existing artifacts found for verification",
            )

        # Use most recent directory
        task_dir = sorted(task_dirs)[-1]
        logger.info(f"Using artifacts from: {task_dir}")

        # Load existing result
        result_file = task_dir / "result_evaluate.json"
        if not result_file.exists():
            result_file = task_dir / "result.json"
        if not result_file.exists():
            logger.error(f"No result file found in {task_dir}")
            return TaskResult(
                task_id=task.task_id,
                goal=task.goal,
                success=False,
                score=None,
                execution_status="error",
                agent_steps=0,
                execution_time_seconds=0.0,
                verification_status="no_result_file",
                error_message="No result file found",
            )

        with open(result_file, 'r', encoding='utf-8') as f:
            existing_result = json.load(f)

        # Build artifacts dict
        artifacts = {}

        # Find downloaded PPTX (should be {task_id}_{timestamp}.pptx)
        pptx_files = list(task_dir.glob("*.pptx"))
        # CLI agents don't drop a downloaded copy in the task dir — the
        # agent's output lives in workspace/output/<task_id>.<ext>.
        if not pptx_files:
            cli_output_dir = task_dir / "workspace" / "output"
            if cli_output_dir.is_dir():
                pptx_files = [
                    p for p in cli_output_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in (".pptx", ".ppt")
                ]
                if pptx_files:
                    logger.info(f"Using CLI agent output from: {cli_output_dir}")
        if pptx_files:
            # Use the most recent if multiple exist
            pptx_file = max(pptx_files, key=lambda p: p.stat().st_mtime)
            artifacts["file"] = pptx_file
            logger.info(f"Found PPTX: {pptx_file}")

            # Look for matching slide images ZIP ({task_id}_{timestamp}.zip)
            slide_images_zip = pptx_file.with_suffix(".zip")
            if slide_images_zip.exists():
                artifacts["images_zip"] = slide_images_zip
                logger.info(f"Found slide images ZIP: {slide_images_zip}")
            else:
                logger.warning(f"No slide images ZIP found at {slide_images_zip}")
        else:
            logger.error("No PPTX file found for verification")

        # Add original file for grading
        artifacts["original_file"] = task.input_file_path

        # Re-grade
        try:
            evaluation_result = task.grader.evaluate(artifacts)
            logger.info(f"Re-grading complete: score={evaluation_result.score}, success={evaluation_result.success}")

            # Create verification result
            result = TaskResult(
                task_id=task.task_id,
                goal=task.goal,
                success=evaluation_result.success,
                score=evaluation_result.score,
                execution_status=existing_result.get("execution_status", "unknown"),
                agent_steps=existing_result.get("agent_steps", 0),
                execution_time_seconds=existing_result.get("execution_time_seconds", 0),
                verification_status="re-verified",
                evaluation_result=evaluation_result,
            )

            # Save verification result
            verification_file = task_dir / f"verification_{int(time.time())}.json"
            with open(verification_file, 'w') as f:
                json.dump(result.to_dict(), f, indent=2)

            logger.info(f"Verification saved to: {verification_file}")
            return result

        except ScreenshotsUnavailableError as e:
            logger.error(f"Re-grading screenshots unavailable: {e}")
            return TaskResult(
                task_id=task.task_id,
                goal=task.goal,
                success=False,
                score=None,
                execution_status="verification_screenshot_unavailable",
                agent_steps=existing_result.get("agent_steps", 0),
                execution_time_seconds=existing_result.get("execution_time_seconds", 0),
                verification_status="screenshot_unavailable",
                error_message=str(e),
            )

        except Exception as e:
            logger.error(f"Re-grading failed: {e}", exc_info=True)
            return TaskResult(
                task_id=task.task_id,
                goal=task.goal,
                success=False,
                score=None,
                execution_status=existing_result.get("execution_status", "unknown"),
                agent_steps=existing_result.get("agent_steps", 0),
                execution_time_seconds=existing_result.get("execution_time_seconds", 0),
                verification_status="grading_failed",
                error_message=str(e),
            )

    def run_task(self, task: Task) -> TaskResult:
        """
        Execute a task and return results.

        Args:
            task: Task to execute

        Returns:
            TaskResult with execution details
        """
        self.current_task = task
        self.step_logs = []
        self.start_time = time.time()

        # Create task-specific directory
        task_dirname = task.task_id
        self.current_task_dir = self.config.results_dir / task_dirname
        self.current_task_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting task: {task.task_id}")
        logger.info(f"Goal: {task.goal}")
        logger.info(f"Results directory: {self.current_task_dir}")

        try:
            # Execute task
            execution_status, agent_steps = self._execute_task(task)

            # Collect artifacts
            artifacts = self._collect_artifacts()

            # Grade results
            evaluation_result = self._grade_task(task, artifacts)

            # Determine success. Defer to the grader's ``success`` flag, which
            # is strict (score == 1.0) for the PPT grader.
            if evaluation_result is None:
                success = False
            else:
                success = (
                    execution_status == "success" and evaluation_result.success
                )

            # Calculate timing
            execution_time = time.time() - self.start_time

            # Generate result
            result = TaskResult(
                task_id=task.task_id,
                goal=task.goal,
                success=success,
                score=evaluation_result.score if evaluation_result else None,
                execution_status=execution_status,
                agent_steps=agent_steps,
                execution_time_seconds=execution_time,
                verification_status="success" if evaluation_result and evaluation_result.success else "failed",
                evaluation_result=evaluation_result,
                screenshots_dir=self.current_task_dir / "screenshots",
                final_file_path=(artifacts.get("file") or artifacts.get("output_file")) if artifacts else None,
                remote_file_path=(artifacts.get("remote_file_path") if artifacts else None),
            )

            # Harvest CLI-agent telemetry (no-op for non-CLI agents).
            self._attach_cli_telemetry(result)

            # Save results
            self._save_results(result)

            logger.info(f"Task completed: {task.task_id}")
            logger.info(f"  Status: {execution_status}")
            logger.info(f"  Steps: {agent_steps}")
            logger.info(f"  Success: {success}")
            logger.info(f"  Score: {result.score}")

            return result

        except ScreenshotsUnavailableError as e:
            # Agent execution succeeded; only the grader's screenshot rendering
            # flaked. Tag distinctly so the retry driver re-verifies without
            # re-running the agent.
            logger.error(f"Verification screenshots unavailable for {task.task_id}: {e}")
            execution_time = time.time() - self.start_time
            result = TaskResult(
                task_id=task.task_id,
                goal=task.goal,
                success=False,
                score=None,
                execution_status="verification_screenshot_unavailable",
                agent_steps=len(self.step_logs),
                execution_time_seconds=execution_time,
                verification_status="screenshot_unavailable",
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )

            # Save error results
            self._save_results(result)

            return result

        except Exception as e:
            logger.error(f"Task execution failed: {task.task_id}")
            logger.error(f"Error: {e}")
            logger.error(traceback.format_exc())

            # Create error result
            execution_time = time.time() - self.start_time
            result = TaskResult(
                task_id=task.task_id,
                goal=task.goal,
                success=False,
                score=None,
                execution_status="infrastructure_failure",
                agent_steps=len(self.step_logs),
                execution_time_seconds=execution_time,
                verification_status="error",
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )

            # Save error results
            self._save_results(result)

            return result

        finally:
            # Cleanup
            self._cleanup()

    def _execute_task(self, task: Task) -> tuple[str, int]:
        """
        Execute task with agent.

        Args:
            task: Task to execute

        Returns:
            Tuple of (execution_status, agent_steps)
        """
        logger.info("Setting up environment...")

        # Pass result directory to environment for artifact storage
        self.environment.result_dir = self.current_task_dir
        if hasattr(self.agent, "action_space") and hasattr(self.environment, "action_space"):
            self.environment.action_space = self.agent.action_space

        # Setup environment with task
        state = self.environment.setup()

        # Set agent instruction
        self.agent.set_instruction(task.goal)

        logger.info("Starting agent loop...")
        logger.info(f"Max steps: {self.config.max_steps}")
        print(f"Max steps configured: {self.config.max_steps}")
        step_count = 0
        max_steps = self.config.max_steps

        # Save initial screenshot
        if self.config.save_screenshots:
            self._save_screenshot(state, step_count)

        # Agent loop. One iteration == one model decision (one Agent.step()
        # call). Agents that batch actions per API call (e.g. GPT-5.x) return
        # a single composite Action whose `sub_actions` are executed together
        # by the action space; this still counts as one step.
        while step_count < max_steps:
            step_count += 1
            logger.info(f"\n--- Step {step_count}/{max_steps} ---")
            print(f"\n--- Step {step_count}/{max_steps} ---")

            step_start = time.time()

            try:
                # Get action from agent
                action = self.agent.step(state)

                step_duration = (time.time() - step_start) * 1000  # milliseconds

                # Log to file
                if action.sub_actions:
                    sub_types = [sa.action_type for sa in action.sub_actions]
                    logger.info(
                        f"Action: batch ({len(action.sub_actions)} sub-actions: {sub_types})"
                    )
                else:
                    logger.info(f"Action: {action.action_type}")
                    logger.info(f"Params: {action.params}")
                if action.reasoning:
                    logger.info(f"Reasoning: {action.reasoning[:200]}...")

                # Also print to console
                if action.sub_actions:
                    sub_types = [sa.action_type for sa in action.sub_actions]
                    print(f"  Action: batch ({len(action.sub_actions)}x) {sub_types}")
                else:
                    print(f"  Action: {action.action_type}")
                    if action.params:
                        params_str = str(action.params)
                        if len(params_str) > 100:
                            params_str = params_str[:100] + "..."
                        print(f"  Params: {params_str}")
                if action.reasoning:
                    reasoning_str = action.reasoning[:150]
                    if len(action.reasoning) > 150:
                        reasoning_str += "..."
                    print(f"  Reasoning: {reasoning_str}")

                # Log step
                screenshot_path = None
                if self.config.save_screenshots and step_count % self.config.screenshot_interval == 0:
                    screenshot_path = self.current_task_dir / "screenshots" / f"step_{step_count:03d}.png"

                step_log = StepLog(
                    step_number=step_count,
                    timestamp=time.time(),
                    action_type=action.action_type,
                    params=action.params,
                    reasoning=action.reasoning,
                    duration_ms=step_duration,
                    screenshot_path=screenshot_path,
                )
                self.step_logs.append(step_log)

                # Check if terminal action
                if action.is_terminal():
                    logger.info(f"Terminal action: {action.action_type}")
                    return ("success", step_count)

                # Execute action in environment
                state = self.environment.update(action)

                # Save screenshot
                if self.config.save_screenshots and step_count % self.config.screenshot_interval == 0:
                    self._save_screenshot(state, step_count)

                # Check if environment indicates done
                if state.done:
                    logger.info("Environment indicates task complete")
                    return ("success", step_count)

            except Exception as e:
                logger.error(f"Error in step {step_count}: {e}")
                logger.error(traceback.format_exc())
                if _looks_like_infra_error(e):
                    logger.error(
                        "Classifying as infrastructure_failure (upstream endpoint / network)"
                    )
                    return ("infrastructure_failure", step_count)
                return ("agent_error", step_count)

        # Max steps reached
        logger.warning(f"Max steps ({max_steps}) reached")
        return ("max_steps", step_count)

    def _collect_artifacts(self) -> dict[str, Path]:
        """
        Collect artifacts from environment.

        Returns:
            Dictionary mapping artifact names to paths
        """
        logger.info("Collecting artifacts...")

        try:
            artifacts = self.environment.download_artifacts()
            logger.info(f"Collected {len(artifacts)} artifacts")
            return artifacts
        except Exception as e:
            logger.error(f"Failed to collect artifacts: {e}")
            return {}

    def _grade_task(self, task: Task, artifacts: dict[str, Path]) -> EvaluationResult | None:
        """
        Grade task completion.

        Args:
            task: Task that was executed
            artifacts: Collected artifacts

        Returns:
            EvaluationResult or None if grading failed
        """
        # Use task's grader (task always has a grader)
        logger.info("Grading task...")
        logger.info(f"Artifacts: {list(artifacts.keys())}")
        for key, path in artifacts.items():
            logger.info(f"  {key}: {path} (exists: {path.exists() if isinstance(path, Path) else 'N/A'})")

        try:
            result = task.grader.evaluate(artifacts)
            logger.info(f"Grading complete: score={result.score}, success={result.success}")
            logger.info(f"Grading reason: {result.reason}")

            # Print to console as well
            print(f"  Score: {result.score}")
            print(f"  Reason: {result.reason[:200]}...")  # Truncate long reasons

            # Save scored rubric to task directory using save_to_file
            try:
                rubric_path = self.current_task_dir / "scored_rubric.json"
                task.grader.rubric_tree.save_to_file(str(rubric_path))
                logger.info(f"Scored rubric saved to: {rubric_path}")
            except Exception as rubric_error:
                logger.warning(f"Failed to save scored rubric: {rubric_error}")

            return result
        except Exception as e:
            logger.error(f"Grading failed: {e}")
            logger.error(traceback.format_exc())

            # Print to console as well
            print(f"  Grading Error: {e}")
            print(f"  Traceback: {traceback.format_exc()[:500]}...")

            return EvaluationResult(
                score=0.0,
                success=False,
                reason=f"Grading error: {str(e)}"
            )

    def _save_screenshot(self, state: State, step: int) -> None:
        """
        Save screenshot from state.

        Args:
            state: Current state
            step: Step number
        """
        from ppteval.core.base import GUIState

        if not isinstance(state, GUIState):
            return

        # Create screenshots directory
        screenshots_dir = self.current_task_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Save screenshot
        screenshot_path = screenshots_dir / f"step_{step:03d}.png"
        with open(screenshot_path, 'wb') as f:
            f.write(state.screenshot)

    def _attach_cli_telemetry(self, result: TaskResult) -> None:
        """Copy CLI telemetry off the agent (if any) onto the TaskResult.

        No-op for non-CLI agents. CLI agents stash a ``CLITelemetry`` dataclass
        on ``self.agent.last_telemetry`` after their single ``step()`` call.
        """
        telemetry = getattr(self.agent, "last_telemetry", None)
        if telemetry is None:
            return
        try:
            telemetry_dict = telemetry.to_dict()
        except AttributeError:
            # Already a dict or unknown type — fall back to dataclasses.asdict.
            try:
                from dataclasses import asdict
                telemetry_dict = asdict(telemetry)
            except Exception:  # noqa: BLE001
                telemetry_dict = dict(telemetry) if isinstance(telemetry, dict) else {}
        result.cli_telemetry = telemetry_dict
        result.agent_turns = telemetry_dict.get("num_turns")
        result.num_tool_calls = telemetry_dict.get("num_tool_calls")
        result.total_tokens = telemetry_dict.get("total_tokens")
        result.cost_usd = telemetry_dict.get("cost_usd")

    def _save_results(self, result: TaskResult) -> None:
        """
        Save task results to disk.

        Args:
            result: TaskResult to save
        """
        logger.info("Saving results...")

        # Convert to dict
        result_dict = result.to_dict()

        # Load and include scored rubric if available
        rubric_path = self.current_task_dir / "scored_rubric.json"
        if rubric_path.exists():
            try:
                with open(rubric_path, 'r', encoding='utf-8') as f:
                    scored_rubric = json.load(f)
                if "evaluation_details" in result_dict and result_dict["evaluation_details"]:
                    result_dict["evaluation_details"]["scored_rubric"] = scored_rubric
                logger.info("Included scored rubric in results")
            except Exception as e:
                logger.warning(f"Failed to load scored rubric: {e}")

        # Save result JSON
        result_path = self.current_task_dir / "result.json"
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result_dict, f, indent=2)
        evaluate_result_path = self.current_task_dir / "result_evaluate.json"
        with open(evaluate_result_path, 'w', encoding='utf-8') as f:
            json.dump(result_dict, f, indent=2)

        # Save action log
        self._save_action_log()

        # Save timing log
        self._save_timing_log()

        # Annotate screenshots
        self._annotate_screenshots()

        logger.info(f"Results saved to: {self.current_task_dir}")

    def _save_action_log(self) -> None:
        """Save action log JSON."""
        actions = []
        for log in self.step_logs:
            actions.append({
                "step": log.step_number,
                "timestamp": log.timestamp,
                "action_type": log.action_type,
                "params": log.params,
                "reasoning": log.reasoning,
                "duration_ms": log.duration_ms,
            })

        action_log_path = self.current_task_dir / "actions.json"
        with open(action_log_path, 'w', encoding='utf-8') as f:
            json.dump(actions, f, indent=2)

    def _save_timing_log(self) -> None:
        """Save timing log."""
        timing_data = {
            "total_time_seconds": time.time() - self.start_time,
            "total_steps": len(self.step_logs),
            "average_step_ms": sum(log.duration_ms for log in self.step_logs) / len(self.step_logs) if self.step_logs else 0,
            "steps": [
                {
                    "step": log.step_number,
                    "duration_ms": log.duration_ms,
                }
                for log in self.step_logs
            ]
        }

        timing_path = self.current_task_dir / "timing.json"
        with open(timing_path, 'w', encoding='utf-8') as f:
            json.dump(timing_data, f, indent=2)

    def _annotate_screenshots(self) -> None:
        """Annotate screenshots with action info, reasoning, and click markers."""
        screenshots_dir = self.current_task_dir / "screenshots"
        if not screenshots_dir.exists():
            return

        annotated_dir = self.current_task_dir / "screenshots_annotated"
        annotated_dir.mkdir(exist_ok=True)

        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            logger.warning("PIL not available, skipping screenshot annotation")
            return

        logger.info("Annotating screenshots...")

        # Try to load a font
        try:
            font = ImageFont.truetype("arial.ttf", 14)
            font_small = ImageFont.truetype("arial.ttf", 12)
        except:
            try:
                font = ImageFont.load_default()
                font_small = font
            except:
                logger.warning("Could not load font, using default")
                font = None
                font_small = None

        for log in self.step_logs:
            screenshot_path = screenshots_dir / f"step_{log.step_number:03d}.png"
            if not screenshot_path.exists():
                continue

            try:
                # Load and copy screenshot
                img = Image.open(screenshot_path).copy()
                draw = ImageDraw.Draw(img)

                # Mark click location if present
                if log.action_type in ["click", "left_click", "double_click", "right_click", "middle_click"]:
                    coordinate = log.params.get("coordinate")
                    if coordinate is None and "x" in log.params and "y" in log.params:
                        coordinate = [log.params["x"], log.params["y"]]
                    if coordinate is not None:
                        x, y = coordinate
                        # Draw crosshair circle
                        radius = 12
                        draw.ellipse([x-radius, y-radius, x+radius, y+radius],
                                   outline='red', width=3)
                        # Draw crosshair lines
                        line_len = 18
                        draw.line([x-line_len, y, x+line_len, y], fill='red', width=3)
                        draw.line([x, y-line_len, x, y+line_len], fill='red', width=3)

                # Prepare text
                action_text = f"Action: {log.action_type}"
                if log.params:
                    # Show key params (limit length)
                    params_display = {}
                    for k, v in log.params.items():
                        if k not in {"coordinate", "x", "y"}:  # Don't show coordinate again
                            params_display[k] = v
                    if params_display:
                        param_str = ", ".join(f"{k}={v}" for k, v in list(params_display.items())[:2])
                        if len(param_str) > 50:
                            param_str = param_str[:50] + "..."
                        action_text += f" ({param_str})"

                reasoning_text = ""
                if log.reasoning:
                    reasoning_text = log.reasoning[:120]
                    if len(log.reasoning) > 120:
                        reasoning_text += "..."

                # Draw text box at bottom with black background
                text_lines = [action_text]
                if reasoning_text:
                    text_lines.append(f"Reasoning: {reasoning_text}")

                # Calculate text size and position
                padding = 10
                line_spacing = 5
                img_width, img_height = img.size

                # Calculate total text height
                if font:
                    line_heights = [font.getbbox(line)[3] - font.getbbox(line)[1] for line in text_lines]
                    total_text_height = sum(line_heights) + line_spacing * (len(text_lines) - 1)
                else:
                    total_text_height = 20 * len(text_lines)

                # Draw background box at bottom
                box_height = total_text_height + padding * 2
                box_top = img_height - box_height
                draw.rectangle([0, box_top, img_width, img_height],
                             fill=(0, 0, 0, 200))

                # Draw text lines
                y_offset = box_top + padding
                for line in text_lines:
                    if font:
                        # Get text size for centering
                        bbox = font.getbbox(line)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                        x_pos = (img_width - text_width) // 2

                        # Draw text with slight outline for better visibility
                        for dx, dy in [(-1,-1), (-1,1), (1,-1), (1,1)]:
                            draw.text((x_pos+dx, y_offset+dy), line, font=font, fill='black')
                        draw.text((x_pos, y_offset), line, font=font, fill='white')

                        y_offset += text_height + line_spacing
                    else:
                        # Fallback without font
                        draw.text((padding, y_offset), line, fill='white')
                        y_offset += 20

                # Save annotated screenshot
                annotated_path = annotated_dir / f"step_{log.step_number:03d}.png"
                img.save(annotated_path)

            except Exception as e:
                logger.warning(f"Failed to annotate screenshot {screenshot_path}: {e}")
                continue

        logger.info(f"Screenshots annotated in: {annotated_dir}")

    def _cleanup(self) -> None:
        """Cleanup resources after task execution."""
        logger.info("Cleaning up...")

        try:
            # Cleanup environment
            self.environment.cleanup()
        except Exception as e:
            logger.error(f"Environment cleanup failed: {e}")

        try:
            # Reset agent
            self.agent.reset()
        except Exception as e:
            logger.error(f"Agent reset failed: {e}")

        # Clear current task
        self.current_task = None
        self.current_task_dir = None
        self.step_logs = []

    def close(self) -> None:
        """Close orchestrator and cleanup all resources."""
        logger.info("Closing orchestrator...")

        try:
            self.environment.cleanup()
        except Exception as e:
            logger.error(f"Environment cleanup failed: {e}")

        try:
            if hasattr(self.agent, 'close'):
                self.agent.close()
        except Exception as e:
            logger.error(f"Agent close failed: {e}")
