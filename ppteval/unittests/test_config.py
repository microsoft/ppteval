"""
Unit tests for ppteval config classes.

Run with: python -m pytest ppteval/unittests/test_config.py
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from ppteval.config import (
    EnvironmentConfig,
    DisplaySize,
    CUAConfig,
    ClaudeConfig,
    UITARSConfig,
    GeminiConfig,
    Qwen3VLConfig,
    OpenCUAConfig,
    OrchestratorConfig,
    resolve_env_var,
)


class TestResolveEnvVar:
    """Tests for environment variable resolution"""

    def test_resolve_env_var_with_braces(self):
        """Test ${VAR_NAME} format"""
        os.environ["TEST_VAR"] = "test_value"
        result = resolve_env_var("${TEST_VAR}")
        assert result == "test_value"

    def test_resolve_env_var_without_braces(self):
        """Test $VAR_NAME format"""
        os.environ["TEST_VAR2"] = "another_value"
        result = resolve_env_var("$TEST_VAR2")
        assert result == "another_value"

    def test_resolve_env_var_missing(self):
        """Test missing environment variable"""
        result = resolve_env_var("${NONEXISTENT_VAR}")
        assert result == ""

    def test_resolve_env_var_plain_string(self):
        """Test plain string (no env var)"""
        result = resolve_env_var("plain_string")
        assert result == "plain_string"


class TestEnvironmentConfig:
    """Tests for EnvironmentConfig"""

    def test_default_config(self):
        """Test default configuration"""
        config = EnvironmentConfig()

        assert config.headless == True
        assert config.resolution == (1024, 768)
        assert config.step_delay == 1.0
        assert config.max_retries == 3
        assert config.onedrive_root == "/PPTEval"

    def test_custom_config(self):
        """Test custom configuration"""
        config = EnvironmentConfig(
            headless=False,
            resolution=(1920, 1080),
            step_delay=0.5
        )

        assert config.headless == False
        assert config.resolution == (1920, 1080)
        assert config.step_delay == 0.5

    def test_from_yaml(self):
        """Test loading from YAML file"""
        yaml_content = """
headless: false
resolution: [1920, 1080]
step_delay: 0.5
max_retries: 5
onedrive_root: "/TestFolder"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            config = EnvironmentConfig.from_yaml(yaml_path)

            assert config.headless == False
            assert config.resolution == (1920, 1080)
            assert config.step_delay == 0.5
            assert config.max_retries == 5
            assert config.onedrive_root == "/TestFolder"
        finally:
            os.unlink(yaml_path)

    def test_to_yaml(self):
        """Test saving to YAML file"""
        config = EnvironmentConfig(
            headless=True,
            resolution=(1024, 768),
            step_delay=1.0
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml_path = f.name

        try:
            config.to_yaml(yaml_path)

            # Load and verify
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f)

            assert data["headless"] == True
            assert data["resolution"] == [1024, 768]
            assert data["step_delay"] == 1.0
        finally:
            os.unlink(yaml_path)


class TestCUAConfig:
    """Tests for CUAConfig"""

    def test_default_config(self):
        """Test default CUA configuration"""
        config = CUAConfig()

        assert config.agent_type == "cua"
        assert config.model_name == "gpt-4o"
        assert config.endpoint == "openai"
        assert config.temperature == 0.7
        assert config.display_size == DisplaySize(width=1024, height=768)

    def test_from_yaml_with_env_var(self):
        """Test loading with environment variable"""
        os.environ["TEST_API_KEY"] = "sk-test-key"

        yaml_content = """
model_name: "gpt-4o"
agent_type: "cua"
endpoint: "openai"
api_key: "${TEST_API_KEY}"
temperature: 0.8
display_size:
  width: 1280
  height: 720
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            config = CUAConfig.from_yaml(yaml_path)

            assert config.api_key == "sk-test-key"
            assert config.temperature == 0.8
            assert config.display_size == DisplaySize(width=1280, height=720)
        finally:
            os.unlink(yaml_path)


class TestClaudeConfig:
    """Tests for ClaudeConfig"""

    def test_default_config(self):
        """Test default Claude configuration"""
        config = ClaudeConfig()

        assert config.agent_type == "claude"
        assert config.model_name == "claude-3-5-sonnet-20241022"
        assert config.base_url == "https://api.anthropic.com"
        assert config.temperature == 1.0
        assert config.max_tokens == 4096
        assert config.computer_use_tool_type == "computer_20250124"
        assert config.computer_use_beta == "computer-use-2025-01-24"

    def test_from_yaml_loads_claude_20251124_tool_fields(self):
        """Test loading newer Claude computer-use tool settings."""
        yaml_content = """
model_name: "claude-opus-4-7"
agent_type: "claude"
api_key: "${TEST_CLAUDE_API_KEY}"
computer_use_tool_type: "computer_20251124"
computer_use_beta: "computer-use-2025-11-24"
display_size:
  width: 1024
  height: 768
"""
        os.environ["TEST_CLAUDE_API_KEY"] = "test-key"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            config = ClaudeConfig.from_yaml(yaml_path)

            assert config.model_name == "claude-opus-4-7"
            assert config.api_key == "test-key"
            assert config.computer_use_tool_type == "computer_20251124"
            assert config.computer_use_beta == "computer-use-2025-11-24"
        finally:
            os.unlink(yaml_path)


class TestUITARSConfig:
    """Tests for UITARSConfig"""

    def test_default_config(self):
        """Test default UITARS configuration"""
        config = UITARSConfig()

        assert config.agent_type == "uitars"
        assert config.model_name == "uitars-v1"
        assert config.temperature == 0.7
        assert config.max_tokens == 4096

    def test_from_yaml_loads_display_dimensions(self):
        """Test loading repo UITARS-style YAML display settings."""
        yaml_content = """
model_name: "uitars-v1"
agent_type: "uitars"
display_size:
  width: 1366
  height: 768
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            config = UITARSConfig.from_yaml(yaml_path)

            assert config.display_size == DisplaySize(width=1366, height=768)
        finally:
            os.unlink(yaml_path)


class TestGeminiConfig:
    """Tests for GeminiConfig"""

    def test_default_config(self):
        """Test default Gemini configuration"""
        config = GeminiConfig()

        assert config.agent_type == "gemini"
        assert config.model_name == "gemini-2.5-computer-use-preview-10-2025"
        assert config.temperature == 0.7
        assert config.top_p == 0.95
        assert config.max_output_tokens == 8192


class TestQwen3VLConfig:
    """Tests for Qwen3VLConfig"""

    def test_default_config(self):
        """Test default Qwen3VL configuration"""
        config = Qwen3VLConfig()

        assert config.agent_type == "qwen3vl"
        assert config.model_name == "qwen/qwen3-vl"
        assert config.coordinate_type == "relative"
        assert config.history_n == 4


class TestOpenCUAConfig:
    """Tests for OpenCUAConfig"""

    def test_default_config(self):
        """Test default OpenCUA configuration"""
        config = OpenCUAConfig()

        assert config.agent_type == "opencua"
        assert config.model_name == "custom_openai/opencua-7b"
        assert config.coordinate_type == "absolute"
        assert config.cot_level == "l2"
        assert config.display_size == DisplaySize(width=1920, height=1080)

    def test_from_yaml_with_env_var(self):
        """Test loading OpenCUA config with environment variables"""
        os.environ["OPENCUA_TEST_KEY"] = "test-opencua-key"

        yaml_content = """
model_name: "custom_openai/opencua-32b"
agent_type: "opencua"
api_key: "${OPENCUA_TEST_KEY}"
base_url: "https://example.test"
display_size:
  width: 1280
  height: 720
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            config = OpenCUAConfig.from_yaml(yaml_path)

            assert config.api_key == "test-opencua-key"
            assert config.model_name == "custom_openai/opencua-32b"
            assert config.display_size == DisplaySize(width=1280, height=720)
        finally:
            os.unlink(yaml_path)


class TestOrchestratorConfig:
    """Tests for OrchestratorConfig"""

    def test_default_config(self):
        """Test default orchestrator configuration"""
        config = OrchestratorConfig(results_dir=Path("/tmp/results"))

        assert config.results_dir == Path("/tmp/results")
        assert config.max_steps == 30
        assert config.enable_logging == True
        assert config.timeout_minutes == 15
        assert config.save_screenshots == True
        assert config.screenshot_interval == 1

    def test_from_yaml(self):
        """Test loading from YAML"""
        yaml_content = """
results_dir: "/tmp/test_results"
max_steps: 50
enable_logging: false
timeout_minutes: 20
save_screenshots: false
screenshot_interval: 2
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            yaml_path = f.name

        try:
            config = OrchestratorConfig.from_yaml(yaml_path)

            assert config.results_dir == Path("/tmp/test_results")
            assert config.max_steps == 50
            assert config.enable_logging == False
            assert config.timeout_minutes == 20
            assert config.save_screenshots == False
            assert config.screenshot_interval == 2
        finally:
            os.unlink(yaml_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
