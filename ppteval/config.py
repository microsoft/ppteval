"""
Configuration classes for ppteval.

This module provides YAML-based configuration with environment variable support:
- DisplaySize: Canonical display resolution configuration
- EnvironmentConfig: Configuration for environments
- CUAConfig: Configuration for OpenAI Computer Use Agent
- ClaudeConfig: Configuration for Anthropic Claude
- UITARSConfig: Configuration for UITARS agent
- GeminiConfig: Configuration for Google Gemini
- Qwen3VLConfig: Configuration for Qwen3-VL
- OpenCUAConfig: Configuration for OpenCUA
- OrchestratorConfig: Configuration for the orchestrator
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml


def resolve_env_var(value: str | None) -> str | None:
    """
    Resolve environment variable in config value.

    Format: ${VAR_NAME} or $VAR_NAME

    Args:
        value: Config value that may contain env var

    Returns:
        Resolved value
    """
    if not isinstance(value, str):
        return value

    if value.startswith("${") and value.endswith("}"):
        # Format: ${VAR_NAME}
        env_var = value[2:-1]
        return os.getenv(env_var, "")
    elif value.startswith("$"):
        # Format: $VAR_NAME
        env_var = value[1:]
        return os.getenv(env_var, "")

    return value


@dataclass
class DisplaySize:
    """Display size shared by agent prompts and sandbox resolution."""
    width: int
    height: int

    @classmethod
    def from_dict(cls, data: dict) -> "DisplaySize":
        """Load display size from YAML/dict data."""
        return cls(width=int(data["width"]), height=int(data["height"]))

    def to_dict(self) -> dict[str, int]:
        """Serialize display size to YAML-compatible data."""
        return {"width": self.width, "height": self.height}


def _load_display_size(value: DisplaySize | dict) -> DisplaySize:
    """Build DisplaySize from nested config data."""
    if isinstance(value, DisplaySize):
        return value
    return DisplaySize.from_dict(value)


def _validate_agent_type(agent_type: str, expected: str) -> None:
    """Ensure config files are loaded with the matching agent family."""
    if agent_type != expected:
        raise ValueError(f"Expected agent_type '{expected}', got '{agent_type}'")


@dataclass
class EnvironmentConfig:
    """Configuration for environments"""
    headless: bool = True
    resolution: tuple[int, int] = (1024, 768)
    step_delay: float = 1.0
    max_retries: int = 3
    onedrive_root: str = "/PPTEval"

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'EnvironmentConfig':
        """Load config from YAML file"""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        # Convert resolution list to tuple
        if "resolution" in data and isinstance(data["resolution"], list):
            data["resolution"] = tuple(data["resolution"])

        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        """Save config to YAML file"""
        data = {
            "headless": self.headless,
            "resolution": list(self.resolution),
            "step_delay": self.step_delay,
            "max_retries": self.max_retries,
            "onedrive_root": self.onedrive_root,
        }

        with open(path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)


@dataclass
class CUAConfig:
    """OpenAI Computer Use Agent configuration"""
    agent_type: Literal["cua"] = "cua"
    model_name: str = "gpt-4o"
    endpoint: Literal["openai", "azure"] = "openai"

    # API settings
    api_key: str | None = None
    base_url: str | None = None
    api_version: str | None = None  # For Azure

    # Model parameters
    temperature: float = 0.7
    top_p: float = 1.0
    truncation: str = "auto"

    # Display settings
    display_size: DisplaySize = field(default_factory=lambda: DisplaySize(width=1024, height=768))
    environment: str = "web-browser"

    def __post_init__(self) -> None:
        """Build DisplaySize from nested config data."""
        _validate_agent_type(self.agent_type, "cua")
        self.display_size = _load_display_size(self.display_size)

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'CUAConfig':
        """Load config from YAML file"""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        # Resolve environment variables
        if "api_key" in data:
            data["api_key"] = resolve_env_var(data["api_key"])
        if "base_url" in data:
            data["base_url"] = resolve_env_var(data["base_url"])
        if "display_size" in data:
            data["display_size"] = _load_display_size(data["display_size"])

        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        """Save config to YAML file"""
        data = {
            "agent_type": self.agent_type,
            "model_name": self.model_name,
            "endpoint": self.endpoint,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "api_version": self.api_version,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "truncation": self.truncation,
            "display_size": self.display_size.to_dict(),
            "environment": self.environment,
        }

        with open(path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)


@dataclass
class GPT5xConfig:
    """OpenAI GPT-5.x Computer Use Agent (GA `computer` tool) configuration.

    Works for both gpt-5.5 and gpt-5.4. Uses the GA `computer` tool which
    returns batched `actions[]` per `computer_call`.
    """
    agent_type: Literal["gpt5x"] = "gpt5x"
    model_name: str = "gpt-5.5"
    endpoint: Literal["openai", "azure"] = "azure"

    # API settings
    api_key: str | None = None
    base_url: str | None = None
    api_version: str | None = None  # For Azure

    # Model parameters
    temperature: float = 0.7
    top_p: float = 1.0
    reasoning_effort: str = "medium"  # low, medium, high

    # Display settings (used only for prompt context; GA tool does not
    # require display dims to be declared)
    display_size: DisplaySize = field(default_factory=lambda: DisplaySize(width=1024, height=768))

    def __post_init__(self) -> None:
        _validate_agent_type(self.agent_type, "gpt5x")
        self.display_size = _load_display_size(self.display_size)

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'GPT5xConfig':
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        if "api_key" in data:
            data["api_key"] = resolve_env_var(data["api_key"])
        if "base_url" in data:
            data["base_url"] = resolve_env_var(data["base_url"])
        if "model_name" in data:
            data["model_name"] = resolve_env_var(data["model_name"]) or data["model_name"]
        if "display_size" in data:
            data["display_size"] = _load_display_size(data["display_size"])

        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        data = {
            "agent_type": self.agent_type,
            "model_name": self.model_name,
            "endpoint": self.endpoint,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "api_version": self.api_version,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "reasoning_effort": self.reasoning_effort,
            "display_size": self.display_size.to_dict(),
        }

        with open(path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)


@dataclass
class ClaudeConfig:
    """Anthropic Claude Computer Use configuration"""
    agent_type: Literal["claude"] = "claude"
    model_name: str = "claude-3-5-sonnet-20241022"

    # API settings
    api_key: str | None = None
    base_url: str = "https://api.anthropic.com"

    # Model parameters
    temperature: float = 1.0
    max_tokens: int = 4096
    reasoning_effort: str = "medium"  # low, medium, high, adaptive
    computer_use_tool_type: Literal["computer_20250124", "computer_20251124"] = "computer_20250124"
    computer_use_beta: str = "computer-use-2025-01-24"

    # Display settings
    display_size: DisplaySize = field(default_factory=lambda: DisplaySize(width=1024, height=768))
    display_number: int | None = None

    def __post_init__(self) -> None:
        """Build DisplaySize from nested config data."""
        _validate_agent_type(self.agent_type, "claude")
        self.display_size = _load_display_size(self.display_size)

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'ClaudeConfig':
        """Load config from YAML file"""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        # Resolve environment variables
        if "api_key" in data:
            data["api_key"] = resolve_env_var(data["api_key"])
        if "base_url" in data:
            data["base_url"] = resolve_env_var(data["base_url"])
        if "display_size" in data:
            data["display_size"] = _load_display_size(data["display_size"])

        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        """Save config to YAML file"""
        data = {
            "agent_type": self.agent_type,
            "model_name": self.model_name,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
            "computer_use_tool_type": self.computer_use_tool_type,
            "computer_use_beta": self.computer_use_beta,
            "display_size": self.display_size.to_dict(),
            "display_number": self.display_number,
        }

        with open(path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)


@dataclass
class UITARSConfig:
    """UITARS agent configuration"""
    agent_type: Literal["uitars"] = "uitars"
    model_name: str = "uitars-v1"

    # API settings
    endpoint_url: str | None = None
    token: str | None = None

    # Model parameters
    temperature: float = 0.7
    max_tokens: int = 4096

    # Request settings
    max_retries: int = 3
    timeout_seconds: int = 60

    # Display settings
    display_size: DisplaySize = field(default_factory=lambda: DisplaySize(width=1024, height=768))

    def __post_init__(self) -> None:
        """Build DisplaySize from nested config data."""
        _validate_agent_type(self.agent_type, "uitars")
        self.display_size = _load_display_size(self.display_size)

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'UITARSConfig':
        """Load config from YAML file"""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        # Resolve environment variables
        if "endpoint_url" in data:
            data["endpoint_url"] = resolve_env_var(data["endpoint_url"])
        if "token" in data:
            data["token"] = resolve_env_var(data["token"])
        if "display_size" in data:
            data["display_size"] = _load_display_size(data["display_size"])

        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        """Save config to YAML file"""
        data = {
            "agent_type": self.agent_type,
            "model_name": self.model_name,
            "endpoint_url": self.endpoint_url,
            "token": self.token,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "display_size": self.display_size.to_dict(),
        }

        with open(path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)


@dataclass
class UITARSVLLMConfig:
    """UI-TARS agent configuration when served by an OpenAI-compatible
    backend such as vLLM (chat completions API with image_url messages).

    The legacy ``UITARSConfig`` calls a bespoke multipart endpoint -- this
    config targets the OpenAI /v1/chat/completions surface instead and
    leaves the legacy code path untouched.
    """

    agent_type: Literal["uitars-vllm"] = "uitars-vllm"
    model_name: str = "uitars-1.5-7b"

    # OpenAI-compatible endpoint
    base_url: str | None = None
    api_key: str | None = None

    # Model parameters
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 1024

    # Request settings
    max_retries: int = 5
    timeout_seconds: int = 120

    # History window (how many past screenshots+responses to send back)
    max_image_history_length: int = 3

    # Display settings (drives resolution + how coordinates are interpreted)
    display_size: DisplaySize = field(default_factory=lambda: DisplaySize(width=1024, height=768))

    def __post_init__(self) -> None:
        _validate_agent_type(self.agent_type, "uitars-vllm")
        self.display_size = _load_display_size(self.display_size)

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'UITARSVLLMConfig':
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        if "base_url" in data:
            data["base_url"] = resolve_env_var(data["base_url"])
        if "api_key" in data:
            data["api_key"] = resolve_env_var(data["api_key"])
        if "display_size" in data:
            data["display_size"] = _load_display_size(data["display_size"])
        return cls(**data)


@dataclass
class GeminiConfig:
    """Google Gemini Computer Use configuration"""
    agent_type: Literal["gemini"] = "gemini"
    model_name: str = "gemini-2.5-computer-use-preview-10-2025"

    # API settings
    api_key: str | None = None

    # Model parameters
    temperature: float = 0.7
    top_p: float = 0.95
    max_output_tokens: int = 8192

    # Display settings - recommended screen size for Computer Use
    display_size: DisplaySize = field(default_factory=lambda: DisplaySize(width=1440, height=900))

    # Computer Use specific
    excluded_actions: list[str] | None = None  # Actions to exclude from computer_use tool

    def __post_init__(self) -> None:
        """Build DisplaySize from nested config data."""
        _validate_agent_type(self.agent_type, "gemini")
        self.display_size = _load_display_size(self.display_size)

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'GeminiConfig':
        """Load config from YAML file"""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        # Resolve environment variables
        if "api_key" in data:
            data["api_key"] = resolve_env_var(data["api_key"])
        if "display_size" in data:
            data["display_size"] = _load_display_size(data["display_size"])

        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        """Save config to YAML file"""
        data = {
            "agent_type": self.agent_type,
            "model_name": self.model_name,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_output_tokens": self.max_output_tokens,
            "display_size": self.display_size.to_dict(),
        }

        with open(path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)


@dataclass
class Qwen3VLConfig:
    """Qwen3-VL agent configuration (uses litellm as backend)"""
    agent_type: Literal["qwen3vl"] = "qwen3vl"
    model_name: str = "qwen/qwen3-vl"

    # API settings (litellm handles provider routing via model name prefix)
    api_key: str | None = None
    base_url: str | None = None

    # Model parameters
    temperature: float = 0.0
    top_p: float = 0.9
    top_k: int | None = None
    # max_tokens = OUTPUT budget. vLLM >=0.12 pre-validates
    # max_input_tokens = max_model_len - max_tokens. Setting max_tokens equal
    # to max_model_len makes the input budget 0 and rejects every request.
    # When None we omit the field entirely and let vLLM auto-budget the
    # output from whatever input fits (legacy behavior).
    max_tokens: int | None = None

    # Thinking mode (for supported providers)
    enable_thinking: bool = False
    thinking_budget: int = 32768

    # Display settings
    display_size: DisplaySize = field(default_factory=lambda: DisplaySize(width=1024, height=768))

    # Agent behavior
    history_n: int = 4  # Number of history steps to include
    coordinate_type: Literal["relative", "absolute"] = "relative"

    # Request settings
    max_retries: int = 5
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        """Build DisplaySize from nested config data."""
        _validate_agent_type(self.agent_type, "qwen3vl")
        self.display_size = _load_display_size(self.display_size)

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'Qwen3VLConfig':
        """Load config from YAML file"""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        # Resolve environment variables
        if "api_key" in data:
            data["api_key"] = resolve_env_var(data["api_key"])
        if "base_url" in data:
            data["base_url"] = resolve_env_var(data["base_url"])
        if "display_size" in data:
            data["display_size"] = _load_display_size(data["display_size"])

        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        """Save config to YAML file"""
        data = {
            "agent_type": self.agent_type,
            "model_name": self.model_name,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_tokens": self.max_tokens,
            "enable_thinking": self.enable_thinking,
            "thinking_budget": self.thinking_budget,
            "display_size": self.display_size.to_dict(),
            "history_n": self.history_n,
            "coordinate_type": self.coordinate_type,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
        }

        with open(path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)


@dataclass
class Qwen3VLOSWorldConfig(Qwen3VLConfig):
    """Qwen3-VL OSWorld-style experimental agent configuration."""
    agent_type: Literal["qwen3vlosworld"] = "qwen3vlosworld"

    def __post_init__(self) -> None:
        """Build DisplaySize from nested config data."""
        _validate_agent_type(self.agent_type, "qwen3vlosworld")
        self.display_size = _load_display_size(self.display_size)


@dataclass
class OpenCUAConfig:
    """OpenCUA agent configuration."""
    agent_type: Literal["opencua"] = "opencua"
    model_name: str = "custom_openai/opencua-7b"

    # API settings
    api_key: str | None = None
    base_url: str | None = None

    # Model parameters
    temperature: float = 0.0
    top_p: float = 0.9
    max_tokens: int = 8096

    # Display settings
    display_size: DisplaySize = field(default_factory=lambda: DisplaySize(width=1920, height=1080))

    # OpenCUA-specific settings
    coordinate_type: Literal["relative", "qwen25", "absolute"] = "absolute"
    cot_level: Literal["l1", "l2", "l3"] = "l2"
    history_type: Literal["action_history", "thought_history", "observation_history"] = "thought_history"
    max_image_history_length: int = 3
    max_steps: int = 30
    password: str = "password"
    use_old_sys_prompt: bool = True

    def __post_init__(self) -> None:
        """Build DisplaySize from nested config data."""
        _validate_agent_type(self.agent_type, "opencua")
        self.display_size = _load_display_size(self.display_size)

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'OpenCUAConfig':
        """Load config from YAML file."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        if "api_key" in data:
            data["api_key"] = resolve_env_var(data["api_key"])
        if "base_url" in data:
            data["base_url"] = resolve_env_var(data["base_url"])
        if "display_size" in data:
            data["display_size"] = _load_display_size(data["display_size"])

        return cls(**data)

    def to_dict(self) -> dict:
        """Convert to a dictionary for agent initialization."""
        return {
            "agent_type": self.agent_type,
            "model_name": self.model_name,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "display_size": self.display_size.to_dict(),
            "coordinate_type": self.coordinate_type,
            "cot_level": self.cot_level,
            "history_type": self.history_type,
            "max_image_history_length": self.max_image_history_length,
            "max_steps": self.max_steps,
            "password": self.password,
            "use_old_sys_prompt": self.use_old_sys_prompt,
        }

    def to_yaml(self, path: Path | str) -> None:
        """Save config to YAML file."""
        with open(path, 'w') as f:
            yaml.safe_dump(self.to_dict(), f, default_flow_style=False)


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator"""
    results_dir: Path
    max_steps: int = 10
    enable_logging: bool = True
    timeout_minutes: int = 15
    save_screenshots: bool = True
    screenshot_interval: int = 1  # Save every N steps

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'OrchestratorConfig':
        """Load config from YAML file"""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        # Convert results_dir to Path
        if "results_dir" in data:
            data["results_dir"] = Path(resolve_env_var(str(data["results_dir"])))

        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        """Save config to YAML file"""
        data = {
            "results_dir": str(self.results_dir),
            "max_steps": self.max_steps,
            "enable_logging": self.enable_logging,
            "timeout_minutes": self.timeout_minutes,
            "save_screenshots": self.save_screenshots,
            "screenshot_interval": self.screenshot_interval,
        }

        with open(path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)


@dataclass
class CLIAgentConfig:
    """Configuration for CLI-driven agents (Claude Code, Copilot CLI, Codex CLI)."""
    agent_type: Literal["cli"] = "cli"
    cli_name: str = "claude-code"           # claude-code | copilot-cli | codex-cli
    binary: str | None = None               # if None, the agent class picks its default
    model: str | None = None
    max_turns: int | None = 40
    send_max_turns: bool = False            # forward --max-turns to the CLI (claude-code only)
    timeout_s: int = 1800
    extra_args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    prices: dict[str, dict[str, float]] | None = None   # codex price table override

    # Optional path (relative to CWD or absolute) to a directory whose
    # contents are copied verbatim into each per-task workspace BEFORE the
    # CLI is invoked. Use this to seed CLI-native customization:
    #   * Claude Code:  CLAUDE.md, .claude/skills/, .claude/agents/, .mcp.json
    #   * Codex CLI:    AGENTS.md, .codex/config.toml
    #   * Copilot CLI:  AGENTS.md, .github/copilot-instructions.md
    # Deterministic files (TASK.md, OUTPUT_INSTRUCTIONS.md, inputs/, output/)
    # always win — they are written after this directory is copied in.
    customization_dir: str | None = None

    # Mirrors other agent configs so run_benchmark plumbing works uniformly,
    # but CLI agents do not use display_size at runtime.
    display_size: DisplaySize = field(default_factory=lambda: DisplaySize(width=1024, height=768))

    def __post_init__(self) -> None:
        _validate_agent_type(self.agent_type, "cli")
        self.display_size = _load_display_size(self.display_size)

    @classmethod
    def from_yaml(cls, path: Path | str) -> 'CLIAgentConfig':
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        if "display_size" in data:
            data["display_size"] = _load_display_size(data["display_size"])
        # Resolve env-var references inside the env dict if any.
        if "env" in data and isinstance(data["env"], dict):
            data["env"] = {k: (resolve_env_var(v) if isinstance(v, str) else v) for k, v in data["env"].items()}
        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        data = {
            "agent_type": self.agent_type,
            "cli_name": self.cli_name,
            "binary": self.binary,
            "model": self.model,
            "max_turns": self.max_turns,
            "send_max_turns": self.send_max_turns,
            "timeout_s": self.timeout_s,
            "extra_args": list(self.extra_args),
            "env": dict(self.env),
            "prices": self.prices,
            "customization_dir": self.customization_dir,
            "display_size": self.display_size.to_dict(),
        }
        with open(path, 'w') as f:
            yaml.safe_dump(data, f, default_flow_style=False)
