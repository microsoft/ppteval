"""
Task and TaskRegistry classes for managing evaluation tasks.

This module provides:
- Task: Represents a single evaluation task with grader
- TaskRegistry: Loads and manages collections of tasks
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ppteval.core.base import Grader


@dataclass
class Task:
    """Represents a single evaluation task"""
    task_id: str
    goal: str
    input_file_path: Path
    grader: Grader
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure input_file_path is a Path object"""
        if isinstance(self.input_file_path, str):
            self.input_file_path = Path(self.input_file_path)


class TaskRegistry:
    """Loads and manages collections of tasks"""

    def __init__(self, registry_path: Path | str):
        """
        Initialize task registry.

        Supports two formats:
        1. Directory with tasks.json file
        2. Directory with individual task subdirectories

        Args:
            registry_path: Path to task registry directory
        """
        self.registry_path = Path(registry_path)
        if not self.registry_path.exists():
            raise ValueError(f"Task registry path does not exist: {self.registry_path}")
        if not self.registry_path.is_dir():
            raise ValueError(f"Task registry path is not a directory: {self.registry_path}")

        # Check which format we're using
        self.tasks_json = self.registry_path / "tasks.json"
        self.use_json_format = self.tasks_json.exists()

    def load(self) -> dict[str, Task]:
        """
        Load all tasks from the registry.

        Returns:
            Dictionary mapping task_id to Task objects
        """
        if self.use_json_format:
            return self._load_from_json()
        else:
            return self._load_from_directories()

    def _load_from_json(self) -> dict[str, Task]:
        """Load tasks from a tasks.json registry file."""
        with open(self.tasks_json, 'r', encoding='utf-8') as f:
            tasks_data = json.load(f)

        tasks = {}
        workspace_root = self.registry_path.parent  # Go up from task_registry to workspace root

        for task_id, task_data in tasks_data.items():
            try:
                # Import here to avoid circular dependency
                from ppteval.graders.ppt_grader import PPTGrader

                task = Task(
                    task_id=task_id,
                    goal=task_data["goal"],
                    input_file_path=workspace_root / task_data["file_path"],
                    grader=PPTGrader(rubric_path=workspace_root / task_data["rubric_path"]),
                    tags=task_data.get("tags", []),
                    metadata=task_data.get("misc", {})
                )
                tasks[task_id] = task
            except Exception as e:
                print(f"Warning: Failed to load task {task_id} from JSON: {e}")
                continue

        return tasks

    def _load_from_directories(self) -> dict[str, Task]:
        """Load tasks from individual task directories."""
        tasks = {}

        # Scan for task directories (each task has its own folder)
        for task_dir in self.registry_path.iterdir():
            if not task_dir.is_dir():
                continue

            # Look for task.json in the directory
            task_file = task_dir / "task.json"
            if not task_file.exists():
                continue

            try:
                task = self._load_task_from_file(task_file, task_dir)
                tasks[task.task_id] = task
            except Exception as e:
                print(f"Warning: Failed to load task from {task_file}: {e}")
                continue

        return tasks

    def _load_task_from_file(self, task_file: Path, task_dir: Path) -> Task:
        """
        Load a single task from a task.json file.

        Args:
            task_file: Path to task.json
            task_dir: Directory containing the task

        Returns:
            Task object
        """
        with open(task_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Extract basic fields
        task_id = data.get("task_id", task_dir.name)
        goal = data.get("goal", data.get("instruction", ""))
        tags = data.get("tags", [])
        metadata = data.get("metadata", {})

        # Find input file
        input_file_name = data.get("input_file", data.get("file_path"))
        if input_file_name:
            input_file_path = task_dir / input_file_name
        else:
            # Try to find .pptx file in task directory
            pptx_files = list(task_dir.glob("*.pptx"))
            if not pptx_files:
                raise ValueError(f"No input file found for task {task_id}")
            input_file_path = pptx_files[0]

        if not input_file_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file_path}")

        # Load grader (will be implemented in Phase 5)
        grader = self._load_grader(task_dir, data)

        return Task(
            task_id=task_id,
            goal=goal,
            input_file_path=input_file_path,
            grader=grader,
            tags=tags,
            metadata=metadata,
        )

    def _load_grader(self, task_dir: Path, task_data: dict[str, Any]) -> Grader:
        """
        Load grader for a task.

        Args:
            task_dir: Task directory
            task_data: Task data from JSON

        Returns:
            Grader instance
        """
        # Import here to avoid circular dependency
        from ppteval.graders.ppt_grader import PPTGrader

        # Look for rubric file
        rubric_path = task_dir / "rubric.json"
        if not rubric_path.exists():
            # Try alternative names
            for alt_name in ["rubric.yaml", "rubric.yml", "grading_rubric.json"]:
                alt_path = task_dir / alt_name
                if alt_path.exists():
                    rubric_path = alt_path
                    break

        if not rubric_path.exists():
            raise FileNotFoundError(f"No rubric file found in {task_dir}")

        return PPTGrader(rubric_path)

    def filter_by_tags(self, tags: list[str]) -> dict[str, Task]:
        """
        Filter tasks by tags.

        Args:
            tags: List of tags to filter by

        Returns:
            Dictionary of tasks that have at least one of the specified tags
        """
        all_tasks = self.load()
        filtered = {}

        for task_id, task in all_tasks.items():
            if any(tag in task.tags for tag in tags):
                filtered[task_id] = task

        return filtered

    def filter_by_ids(self, task_ids: list[str]) -> dict[str, Task]:
        """
        Filter tasks by task IDs.

        Args:
            task_ids: List of task IDs to include

        Returns:
            Dictionary of tasks matching the IDs
        """
        all_tasks = self.load()
        filtered = {}

        for task_id in task_ids:
            if task_id in all_tasks:
                filtered[task_id] = all_tasks[task_id]

        return filtered
