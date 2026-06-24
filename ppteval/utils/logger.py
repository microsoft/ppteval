"""
Centralized logging system for ppteval.

Provides structured logging for task execution with:
- Action logging with timestamps
- Screenshot management
- Timing information
- JSON result files
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ppteval.core.base import Action, State, GUIState


class TaskLogger:
    """
    Logger for a single task execution.

    Logs actions, states, timing, and creates structured output files.
    """

    def __init__(self, task_id: str, log_dir: Path, save_screenshots: bool = True):
        """
        Initialize task logger.

        Args:
            task_id: Unique identifier for the task
            log_dir: Directory to save log files
            save_screenshots: Whether to save screenshots
        """
        self.task_id = task_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.save_screenshots = save_screenshots

        # Create subdirectories
        self.screenshots_dir = self.log_dir / "screenshots"
        if self.save_screenshots:
            self.screenshots_dir.mkdir(exist_ok=True)

        # Log files
        self.log_file = self.log_dir / f"{task_id}.log"
        self.actions_file = self.log_dir / f"{task_id}_actions.json"

        # Initialize logger
        self.logger = self._setup_logger()

        # Tracking
        self.start_time: float | None = None
        self.actions: list[dict[str, Any]] = []
        self.step_counter = 0

    def _setup_logger(self) -> logging.Logger:
        """Set up file and console logging."""
        logger = logging.getLogger(f"ppteval.task.{self.task_id}")
        logger.setLevel(logging.DEBUG)

        # Clear existing handlers
        logger.handlers.clear()

        # File handler
        file_handler = logging.FileHandler(self.log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    def start_task(self, goal: str, input_file: Path):
        """Log task start."""
        self.start_time = time.time()

        self.logger.info("=" * 80)
        self.logger.info(f"🚀 TASK STARTED: {self.task_id}")
        self.logger.info(f"📋 Goal: {goal}")
        self.logger.info(f"📁 Input: {input_file}")
        self.logger.info(f"⏰ Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 80)

    def log_action(self, step: int, action: Action):
        """
        Log an action taken by the agent.

        Args:
            step: Step number
            action: Action object
        """
        current_time = time.time()
        elapsed = current_time - self.start_time if self.start_time else 0

        action_data = {
            "step": step,
            "timestamp": current_time,
            "elapsed_seconds": elapsed,
            "action_type": action.action_type,
            "params": action.params,
            "reasoning": action.reasoning,
        }

        self.actions.append(action_data)

        # Log to file
        self.logger.info(f"Step {step}: {action.action_type}")
        if action.reasoning:
            self.logger.debug(f"  Reasoning: {action.reasoning}")
        self.logger.debug(f"  Params: {action.params}")

        # Save actions incrementally
        with open(self.actions_file, 'w', encoding='utf-8') as f:
            json.dump(self.actions, f, indent=2)

    def log_state(self, step: int, state: State):
        """
        Log environment state.

        Args:
            step: Step number
            state: State object
        """
        self.logger.debug(f"State after step {step}: done={state.done}")

        # Save screenshot if it's a GUIState
        if isinstance(state, GUIState) and self.save_screenshots:
            screenshot_path = self.screenshots_dir / f"step_{step:03d}.png"
            with open(screenshot_path, 'wb') as f:
                f.write(state.screenshot)
            self.logger.debug(f"  Screenshot saved: {screenshot_path.name}")

    def log_error(self, message: str, exception: Exception | None = None):
        """Log an error."""
        self.logger.error(message)
        if exception:
            self.logger.exception(exception)

    def log_info(self, message: str):
        """Log an info message."""
        self.logger.info(message)

    def log_debug(self, message: str):
        """Log a debug message."""
        self.logger.debug(message)

    def end_task(self, success: bool, message: str | None = None):
        """Log task completion."""
        end_time = time.time()
        duration = end_time - self.start_time if self.start_time else 0

        status = "[ok] SUCCESS" if success else "[error] FAILED"
        self.logger.info("=" * 80)
        self.logger.info(f"{status}: {self.task_id}")
        if message:
            self.logger.info(f"Message: {message}")
        self.logger.info(f"Duration: {duration:.2f}s")
        self.logger.info(f"Total steps: {len(self.actions)}")
        self.logger.info("=" * 80)

    def close(self):
        """Close logger and handlers."""
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)


class CentralLogger:
    """
    Central logger that creates task-specific loggers.

    Manages logging for the entire orchestrator run.
    """

    def __init__(self, results_dir: Path):
        """
        Initialize central logger.

        Args:
            results_dir: Root directory for all results
        """
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Main orchestrator logger
        self.logger = self._setup_logger()

        # Track task loggers
        self.task_loggers: dict[str, TaskLogger] = {}

    def _setup_logger(self) -> logging.Logger:
        """Set up orchestrator logger."""
        logger = logging.getLogger("ppteval.orchestrator")
        logger.setLevel(logging.INFO)

        # Clear existing handlers
        logger.handlers.clear()

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)

        logger.addHandler(console_handler)

        return logger

    def create_task_logger(
        self,
        task_id: str,
        task_dir: Path,
        save_screenshots: bool = True
    ) -> TaskLogger:
        """
        Create a logger for a specific task.

        Args:
            task_id: Task identifier
            task_dir: Directory for task logs
            save_screenshots: Whether to save screenshots

        Returns:
            TaskLogger instance
        """
        task_logger = TaskLogger(task_id, task_dir, save_screenshots)
        self.task_loggers[task_id] = task_logger
        return task_logger

    def info(self, message: str):
        """Log info message to orchestrator logger."""
        self.logger.info(message)

    def error(self, message: str, exception: Exception | None = None):
        """Log error message to orchestrator logger."""
        self.logger.error(message)
        if exception:
            self.logger.exception(exception)

    def close_task_logger(self, task_id: str):
        """Close a specific task logger."""
        if task_id in self.task_loggers:
            self.task_loggers[task_id].close()
            del self.task_loggers[task_id]
