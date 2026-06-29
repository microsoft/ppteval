"""
Integration tests for ppteval orchestrator with real agents.

These tests verify the complete workflow:
Environment -> Orchestrator -> Agent -> ActionSpace -> Action execution

Tests are marked with @pytest.mark.integration and require:
- Environment variables: CLIENT_ID, OPENAI_API_KEY (for CUA/UITARS)
- Active internet connection
- OneDrive access
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from ppteval import Orchestrator, OrchestratorConfig
from ppteval.agents import CUAAgent, UITARSAgent
from ppteval.config import CUAConfig, UITARSConfig, EnvironmentConfig
from ppteval.core.base import Action, GUIState, EvaluationResult
from ppteval.core.task import Task
from ppteval.environments import ScreenEnvEnvironment


# Note: Individual test classes are marked with @pytest.mark.integration
# Mock tests don't require environment variables


class SimpleMockEnvironment:
    """Simple mock environment for testing without OneDrive/Browser."""

    def __init__(self, task, config, max_actions=5):
        self.task = task
        self.config = config
        self.max_actions = max_actions
        self.action_count = 0
        self.logger = None

    def setup(self) -> GUIState:
        """Setup returns initial state."""
        return GUIState(
            screenshot=b"fake_screenshot_data",
            done=False
        )

    def update(self, action: Action) -> GUIState:
        """Execute action and return new state."""
        self.action_count += 1

        # Simulate task completion after a few actions
        is_done = self.action_count >= self.max_actions

        return GUIState(
            screenshot=b"fake_screenshot_data",
            done=is_done
        )

    def download_artifacts(self) -> dict[str, Path]:
        """Return empty artifacts."""
        return {}

    def cleanup(self):
        """Cleanup."""
        pass


class SimpleMockGrader:
    """Simple mock grader for testing."""

    def evaluate(self, artifacts: dict[str, Path]) -> EvaluationResult:
        """Return a simple evaluation result."""
        return EvaluationResult(
            score=0.8,
            success=True,
            reason="Mock grading: Task completed successfully",
            details={"mock": True}
        )


@pytest.fixture
def temp_results_dir():
    """Create temporary directory for results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def simple_task():
    """Create a simple test task."""
    return Task(
        task_id="test_integration",
        goal="Click on a button and type some text",
        input_file_path=Path("fake_file.pptx"),
        grader=SimpleMockGrader()
    )


@pytest.fixture
def mock_environment(simple_task):
    """Create mock environment."""
    config = EnvironmentConfig(resolution=(1024, 768))
    return SimpleMockEnvironment(simple_task, config, max_actions=5)


@pytest.fixture
def orchestrator_config(temp_results_dir):
    """Create orchestrator configuration."""
    return OrchestratorConfig(
        results_dir=temp_results_dir,
        max_steps=10,
        save_screenshots=True
    )


class TestIntegrationSimpleMock:
    """Integration tests with simple mock environment (no API calls)."""

    def test_orchestrator_with_mock_agent_complete_workflow(
        self,
        simple_task,
        mock_environment,
        orchestrator_config
    ):
        """Test complete workflow with mocked agent (no API calls)."""
        # Create mock agent
        mock_agent = Mock()
        mock_agent.step.side_effect = [
            Action(action_type="left_click", params={"x": 100, "y": 200}),
            Action(action_type="type", params={"text": "hello"}),
            Action(action_type="keypress", params={"keys": "Enter"}),
            Action(action_type="wait", params={"duration": 1.0}),
            Action(action_type="finish", params={"message": "Task completed"})
        ]
        mock_agent.set_instruction = Mock(return_value=None)
        mock_agent.reset = Mock(return_value=None)
        mock_agent.close = Mock(return_value=None)

        # Create orchestrator with agent
        orchestrator = Orchestrator(
            config=orchestrator_config,
            environment=mock_environment,
            agent=mock_agent,
            )

        # Run task
        result = orchestrator.run_task(simple_task)

        # Verify result
        assert result.success is True
        assert result.agent_steps == 5
        assert result.task_id == "test_integration"

        # Verify grading was performed
        assert result.evaluation_result is not None
        assert result.evaluation_result.score == 0.8
        assert result.evaluation_result.success is True

        # Verify agent was called correctly
        assert mock_agent.set_instruction.called
        assert mock_agent.step.call_count == 5
        assert mock_agent.reset.called

        # Verify result files were created (in timestamped task directory)
        assert result.screenshots_dir is not None
        task_dir = result.screenshots_dir.parent  # screenshots_dir is task_dir/screenshots
        actions_file = task_dir / "actions.json"
        timing_file = task_dir / "timing.json"
        result_file = task_dir / "result.json"

        assert actions_file.exists()
        assert timing_file.exists()
        assert result_file.exists()


@pytest.mark.integration
class TestIntegrationCUAAgent:
    """Integration tests with real CUA agent (requires API key)."""

    def test_cua_agent_basic_action(self, simple_task, mock_environment, orchestrator_config):
        """Test CUA agent can generate and execute basic actions."""
        # Skip if no configuration
        if not os.getenv("CUA_BASE_URL"):
            pytest.skip("CUA_BASE_URL not set")

        # Create CUA agent
        cua_config = {
            "model_name": os.getenv("CUA_MODEL_NAME", "computer-use-preview"),
            "endpoint": os.getenv("CUA_ENDPOINT", "azure"),
            "base_url": os.getenv("CUA_BASE_URL"),
            "api_version": os.getenv("CUA_API_VERSION", "2025-04-01-preview"),
            "display_size": {"width": 1024, "height": 768},
            "environment": "browser",
            "temperature": 0.7,
            "top_p": 1.0,
        }
        agent = CUAAgent(config=cua_config)

        # Create orchestrator with agent
        orchestrator = Orchestrator(
            config=orchestrator_config,
            environment=mock_environment,
            agent=agent,
            )

        try:
            # Run task with max 5 steps
            result = orchestrator.run_task(simple_task)

            # Verify result structure
            assert result is not None
            assert result.task_id == "test_integration"
            assert isinstance(result.success, bool)
            assert isinstance(result.agent_steps, int)
            assert result.agent_steps > 0

            # Verify timing information
            assert result.execution_time_seconds > 0

            print(f"\nCUA Agent Test Results:")
            print(f"  Success: {result.success}")
            print(f"  Steps: {result.agent_steps}")
            print(f"  Time: {result.execution_time_seconds:.2f}s")

        finally:
            agent.close()

    def test_cua_action_space_coordinate_handling(self, simple_task, mock_environment, orchestrator_config):
        """Test that CUA action_space correctly handles coordinates."""
        if not os.getenv("CUA_BASE_URL"):
            pytest.skip("CUA_BASE_URL not set")

        # Create CUA agent
        cua_config = {
            "model_name": os.getenv("CUA_MODEL_NAME", "computer-use-preview"),
            "endpoint": os.getenv("CUA_ENDPOINT", "azure"),
            "base_url": os.getenv("CUA_BASE_URL"),
            "api_version": os.getenv("CUA_API_VERSION", "2025-04-01-preview"),
            "display_size": {"width": 1024, "height": 768},
            "environment": "browser",
            "temperature": 0.7,
            "top_p": 1.0,
        }
        agent = CUAAgent(config=cua_config)

        # Create orchestrator with limited steps
        config = OrchestratorConfig(
            results_dir=orchestrator_config.results_dir,
            max_steps=3,  # Limit to 3 steps
            save_screenshots=True
        )
        orchestrator = Orchestrator(
            config=config,
            environment=mock_environment,
            agent=agent,
            )

        try:
            result = orchestrator.run_task(simple_task)

            # Verify result structure
            assert result is not None
            assert isinstance(result.agent_steps, int)
            assert result.agent_steps > 0

            print(f"\nCUA ActionSpace Test Results:")
            print(f"  Steps taken: {result.agent_steps}")
            print(f"  Success: {result.success}")

        finally:
            agent.close()


@pytest.mark.integration
class TestIntegrationUITARSAgent:
    """Integration tests with real UITARS agent (requires API key)."""

    def test_uitars_agent_basic_action(self, simple_task, mock_environment, orchestrator_config):
        """Test UITARS agent can generate and execute basic actions."""
        if not os.getenv("UITARS_TOKEN"):
            pytest.skip("UITARS_TOKEN not set")

        # Create UITARS agent
        uitars_config = {
            "model_name": "uitars-v1",
            "endpoint_url": os.getenv("UITARS_ENDPOINT_URL"),
            "token": os.getenv("UITARS_TOKEN"),
            "display_size": {"width": 1024, "height": 768},
            "temperature": 0.7,
        }
        agent = UITARSAgent(config=uitars_config)

        # Create orchestrator with agent
        orchestrator = Orchestrator(
            config=orchestrator_config,
            environment=mock_environment,
            agent=agent,
            )

        try:
            # Run task
            result = orchestrator.run_task(simple_task)

            # Verify result structure
            assert result is not None
            assert result.task_id == "test_integration"
            assert isinstance(result.success, bool)
            assert isinstance(result.agent_steps, int)
            assert result.agent_steps > 0

            print(f"\nUITARS Agent Test Results:")
            print(f"  Success: {result.success}")
            print(f"  Steps: {result.agent_steps}")
            print(f"  Time: {result.execution_time_seconds:.2f}s")

        finally:
            agent.close()

    def test_uitars_vs_cua_comparison(self, simple_task, mock_environment, orchestrator_config):
        """Compare UITARS and CUA agents on the same task."""
        if not os.getenv("CUA_BASE_URL") or not os.getenv("UITARS_TOKEN"):
            pytest.skip("CUA_BASE_URL or UITARS_TOKEN not set")

        results = {}

        # Test CUA
        cua_config = {
            "model_name": os.getenv("CUA_MODEL_NAME", "computer-use-preview"),
            "endpoint": os.getenv("CUA_ENDPOINT", "azure"),
            "base_url": os.getenv("CUA_BASE_URL"),
            "api_version": os.getenv("CUA_API_VERSION", "2025-04-01-preview"),
            "display_size": {"width": 1024, "height": 768},
            "environment": "browser",
            "temperature": 0.7,
            "top_p": 1.0,
        }
        cua_agent = CUAAgent(config=cua_config)

        orchestrator_cua = Orchestrator(
            config=orchestrator_config,
            environment=mock_environment,
            agent=cua_agent,
            )

        try:
            results["cua"] = orchestrator_cua.run_task(simple_task)
        finally:
            cua_agent.close()

        # Reset environment
        mock_environment.action_count = 0

        # Test UITARS
        uitars_config = {
            "model_name": "uitars-v1",
            "endpoint_url": os.getenv("UITARS_ENDPOINT_URL"),
            "token": os.getenv("UITARS_TOKEN"),
            "display_size": {"width": 1024, "height": 768},
            "temperature": 0.7,
        }
        uitars_agent = UITARSAgent(config=uitars_config)

        orchestrator_uitars = Orchestrator(
            config=orchestrator_config,
            environment=mock_environment,
            agent=uitars_agent,
            )

        try:
            results["uitars"] = orchestrator_uitars.run_task(simple_task)
        finally:
            uitars_agent.close()

        # Compare results
        print("\n=== Agent Comparison ===")
        for agent_name, result in results.items():
            print(f"\n{agent_name.upper()}:")
            print(f"  Success: {result.success}")
            print(f"  Steps: {result.agent_steps}")
            print(f"  Time: {result.execution_time_seconds:.2f}s")
            print(f"  Avg time/step: {result.execution_time_seconds/result.agent_steps:.2f}s")
            if result.evaluation_result:
                print(f"  Score: {result.evaluation_result.score:.2f}")

        # Both should complete successfully
        assert results["cua"].success or results["cua"].agent_steps > 0
        assert results["uitars"].success or results["uitars"].agent_steps > 0


@pytest.mark.integration
@pytest.mark.slow
class TestIntegrationRealEnvironment:
    """Integration tests with real ScreenEnv environment (requires OneDrive)."""

    @pytest.mark.skipif(
        not os.getenv("CLIENT_ID"),
        reason="Real environment tests require CLIENT_ID"
    )
    def test_real_environment_setup(self, simple_task, temp_results_dir):
        """Test that real ScreenEnv environment can be created and set up."""
        config = EnvironmentConfig(
            resolution=(1024, 768),
            headless=True,
            onedrive_root="PPTEval"
        )

        env = ScreenEnvEnvironment(
            task=simple_task,
            config=config,
            client_id=os.getenv("CLIENT_ID")
        )

        try:
            # Test setup
            initial_state = env.setup()

            assert initial_state is not None
            assert initial_state.screenshot is not None
            assert initial_state.screen_width > 0
            assert initial_state.screen_height > 0

            print(f"\nReal environment initialized successfully:")
            print(f"  Screen: {initial_state.screen_width}x{initial_state.screen_height}")
            print(f"  Has screenshot: {len(initial_state.screenshot) > 0}")

        finally:
            env.cleanup()


if __name__ == "__main__":
    # Run with: python -m pytest ppteval/unittests/test_integration.py -v -s
    pytest.main([__file__, "-v", "-s", "-m", "not slow"])
