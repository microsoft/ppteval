"""Shared state for task proposal agents."""

from contextvars import ContextVar

proposed_tasks: ContextVar[list[str]] = ContextVar("proposed_tasks", default=[])


def add_tasks_to_dataset(tasks: list[str]) -> None:
    """Record generated task proposals for the current proposal run."""
    proposed_tasks.get().extend(tasks)
