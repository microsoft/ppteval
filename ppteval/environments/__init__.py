"""Environments for task execution."""

from ppteval.environments.cli_workspace_environment import CLIWorkspaceEnvironment

__all__ = [
    "ScreenEnvEnvironment",
    "CLIWorkspaceEnvironment",
]


def __getattr__(name):
    # Lazy-import ScreenEnvEnvironment because the underlying ``screenenv``
    # package eagerly instantiates a Docker client at import time. Pure-host
    # codepaths (e.g. the CLI agents) must not require Docker.
    if name == "ScreenEnvEnvironment":
        from ppteval.environments.screenenv_environment import ScreenEnvEnvironment
        return ScreenEnvEnvironment
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
