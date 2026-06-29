"""
Unit tests for Orchestrator.

Tests orchestrator functionality with mocked components.
"""

import json
import pytest
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from ppteval.config import OrchestratorConfig
from ppteval.core.base import (
    Action,
    Agent,
    Environment,
    EvaluationResult,
    GUIState,
    Grader,
    TaskResult,
)
from ppteval.core.task import Task
from ppteval.orchestrator import Orchestrator


@pytest.fixture
def temp_results_dir(tmp_path):
    """Create temporary results directory."""
    return tmp_path / "results"


@pytest.fixture
def config(temp_results_dir):
    """Create orchestrator config."""
    return OrchestratorConfig(
        results_dir=temp_results_dir,
        max_steps=10,
        enable_logging=True,
        timeout_minutes=5,
        save_screenshots=True,
        screenshot_interval=1,
    )


@pytest.fixture
def mock_environment():
    """Create mock environment."""
    env = Mock(spec=Environment)
    env.setup.return_value = GUIState(screenshot=b"screenshot", done=False)
    env.update.return_value = GUIState(screenshot=b"screenshot", done=False)
    env.download_artifacts.return_value = {"file": Path("/fake/output.pptx")}
    env.cleanup.return_value = None
    return env


@pytest.fixture
def mock_agent():
    """Create mock agent."""
    agent = Mock()
    agent.step = Mock(return_value=Action(action_type="finish", params={"message": "done"}))
    agent.set_instruction = Mock(return_value=None)
    agent.reset = Mock(return_value=None)
    agent.close = Mock(return_value=None)
    return agent


@pytest.fixture
def mock_grader():
    """Create mock grader."""
    grader = Mock(spec=Grader)
    grader.evaluate.return_value = EvaluationResult(
        score=1.0,
        success=True,
        reason="Task completed successfully"
    )
    return grader


@pytest.fixture
def mock_task(mock_grader):
    """Create mock task with grader."""
    task = Task(
        task_id="test-001",
        goal="Complete the test task",
        input_file_path=Path("/fake/input.pptx"),
        grader=mock_grader,
        tags=["test"],
        metadata={}
    )
    return task


class TestOrchestratorInit:
    """Tests for Orchestrator initialization."""

    def test_init_creates_results_dir(self, config, mock_environment, mock_agent):
        """Test that orchestrator creates results directory."""
        orchestrator = Orchestrator(config, mock_environment, mock_agent)

        assert config.results_dir.exists()
        assert orchestrator.config == config
        assert orchestrator.environment == mock_environment
        assert orchestrator.agent == mock_agent

    def test_init_with_config(self, config, mock_environment, mock_agent):
        """Test orchestrator initialization with config."""
        orchestrator = Orchestrator(config, mock_environment, mock_agent)

        assert orchestrator.config == config
        assert orchestrator.environment == mock_environment
        assert orchestrator.agent == mock_agent


class TestTaskExecution:
    """Tests for task execution."""

    def test_run_task_success(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test successful task execution."""
        # Agent returns finish action after 3 steps
        mock_agent.step.side_effect = [
            Action(action_type="left_click", params={"coordinate": [100, 200]}),
            Action(action_type="type", params={"text": "test"}),
            Action(action_type="finish", params={"message": "done"}),
        ]

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        assert result.success is True
        assert result.execution_status == "success"
        assert result.agent_steps == 3
        assert result.score == 1.0
        assert result.verification_status == "success"

        # Verify calls
        mock_environment.setup.assert_called_once()
        mock_agent.set_instruction.assert_called_once_with(mock_task.goal)
        assert mock_agent.step.call_count == 3
        mock_grader.evaluate.assert_called_once()
        mock_environment.cleanup.assert_called_once()
        mock_agent.reset.assert_called_once()

    def test_run_task_max_steps(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test task hitting max steps limit."""
        # Agent never returns finish action
        mock_agent.step.return_value = Action(action_type="left_click", params={"coordinate": [100, 200]})

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        assert result.execution_status == "max_steps"
        assert result.agent_steps == 10  # max_steps from config
        assert mock_agent.step.call_count == 10

    def test_run_task_agent_error(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test task with agent error."""
        # Agent raises exception
        mock_agent.step.side_effect = ValueError("Agent error")

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        assert result.execution_status == "agent_error"
        assert result.agent_steps == 1

    def test_run_task_environment_done(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test task where environment signals done."""
        # Agent returns action
        mock_agent.step.return_value = Action(action_type="left_click", params={"coordinate": [100, 200]})

        # Environment signals done after update
        mock_environment.update.return_value = GUIState(screenshot=b"screenshot", done=True)

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        assert result.execution_status == "success"
        assert result.agent_steps == 1


class TestArtifactCollection:
    """Tests for artifact collection."""

    def test_collect_artifacts_success(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test successful artifact collection."""
        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})

        artifacts = {"file": Path("/fake/output.pptx")}
        mock_environment.download_artifacts.return_value = artifacts

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        mock_environment.download_artifacts.assert_called_once()
        assert result.final_file_path == artifacts["file"]

    def test_collect_artifacts_failure(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test artifact collection failure."""
        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})
        mock_environment.download_artifacts.side_effect = Exception("Download failed")

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        # Should handle error gracefully
        assert result.final_file_path is None


class TestGrading:
    """Tests for grading."""

    def test_grading_success(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test successful grading."""
        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})

        grading_result = EvaluationResult(score=0.8, success=True, reason="Mostly correct")
        mock_grader.evaluate.return_value = grading_result

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        assert result.score == 0.8
        assert result.evaluation_result == grading_result

    def test_grading_failure(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test grading indicating failure."""
        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})

        grading_result = EvaluationResult(score=0.0, success=False, reason="Incorrect")
        mock_grader.evaluate.return_value = grading_result

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        assert result.success is False
        assert result.score == 0.0
        assert result.verification_status == "failed"

    def test_grading_error(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test grading raises exception."""
        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})
        mock_grader.evaluate.side_effect = Exception("Grading error")

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        # Should create error evaluation result
        assert result.evaluation_result is not None
        assert result.evaluation_result.success is False
        assert "Grading error" in result.evaluation_result.reason

    def test_grading_with_custom_grader(self, config, mock_environment, mock_agent):
        """Test execution with a custom grader that returns specific score."""
        # Create custom grader
        custom_grader = Mock(spec=Grader)
        custom_grader.evaluate.return_value = EvaluationResult(
            score=0.5,
            success=True,
            reason="Partial completion"
        )

        # Create task with custom grader
        task = Task(
            task_id="test-custom-grader",
            goal="Test with custom grader",
            input_file_path=Path("/fake/input.pptx"),
            grader=custom_grader
        )

        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(task)

        assert result.evaluation_result is not None
        assert result.score == 0.5
        assert result.evaluation_result.reason == "Partial completion"


class TestResultSaving:
    """Tests for result saving."""

    def test_save_results_creates_files(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test that results are saved to files."""
        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        # Check that result directory was created
        assert result.screenshots_dir.parent.exists()

        # Check that both canonical and compatibility result files exist
        result_file = result.screenshots_dir.parent / "result.json"
        evaluate_result_file = result.screenshots_dir.parent / "result_evaluate.json"
        assert result_file.exists()
        assert evaluate_result_file.exists()

        # Verify JSON content
        with open(result_file, 'r') as f:
            data = json.load(f)

        assert data["task_id"] == "test-001"
        assert data["execution_status"] == "success"

    def test_save_action_log(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test that action log is saved."""
        mock_agent.step.side_effect = [
            Action(action_type="left_click", params={"coordinate": [100, 200]}, reasoning="Click button"),
            Action(action_type="finish", params={"message": "done"}),
        ]

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        # Check actions.json
        action_file = result.screenshots_dir.parent / "actions.json"
        assert action_file.exists()

        with open(action_file, 'r') as f:
            actions = json.load(f)

        assert len(actions) == 2
        assert actions[0]["action_type"] == "left_click"
        assert actions[0]["reasoning"] == "Click button"

    def test_save_timing_log(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test that timing log is saved."""
        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        # Check timing.json
        timing_file = result.screenshots_dir.parent / "timing.json"
        assert timing_file.exists()

        with open(timing_file, 'r') as f:
            timing = json.load(f)

        assert "total_time_seconds" in timing
        assert "total_steps" in timing
        assert timing["total_steps"] == 1


class TestScreenshots:
    """Tests for screenshot saving."""

    def test_save_screenshots_enabled(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test screenshots are saved when enabled."""
        mock_agent.step.side_effect = [
            Action(action_type="left_click", params={"coordinate": [100, 200]}),
            Action(action_type="finish", params={"message": "done"}),
        ]

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        # Check screenshots directory
        assert result.screenshots_dir.exists()

        # Check initial screenshot
        initial_screenshot = result.screenshots_dir / "step_000.png"
        assert initial_screenshot.exists()

        # Check step screenshots
        step1_screenshot = result.screenshots_dir / "step_001.png"
        assert step1_screenshot.exists()

    def test_save_screenshots_disabled(self, temp_results_dir, mock_environment, mock_agent, mock_grader, mock_task):
        """Test screenshots not saved when disabled."""
        config = OrchestratorConfig(
            results_dir=temp_results_dir,
            max_steps=10,
            save_screenshots=False,
        )

        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        # Screenshots directory may exist but should be empty
        if result.screenshots_dir.exists():
            assert len(list(result.screenshots_dir.iterdir())) == 0


class TestCleanup:
    """Tests for cleanup."""

    def test_cleanup_called(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test cleanup is called after task."""
        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        orchestrator.run_task(mock_task)

        mock_environment.cleanup.assert_called_once()
        mock_agent.reset.assert_called_once()

    def test_cleanup_handles_errors(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test cleanup handles errors gracefully."""
        mock_agent.step.return_value = Action(action_type="finish", params={"message": "done"})
        mock_environment.cleanup.side_effect = Exception("Cleanup error")
        mock_agent.reset.side_effect = Exception("Reset error")

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        # Should complete despite cleanup errors
        assert result.execution_status == "success"

    def test_close_orchestrator(self, config, mock_environment, mock_agent):
        """Test closing orchestrator."""
        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        orchestrator.close()

        mock_environment.cleanup.assert_called()
        mock_agent.close.assert_called()


class TestErrorHandling:
    """Tests for error handling."""

    def test_infrastructure_failure(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test infrastructure failure is captured."""
        # Setup raises exception
        mock_environment.setup.side_effect = Exception("Setup failed")

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        assert result.execution_status == "infrastructure_failure"
        assert result.success is False
        assert "Setup failed" in result.error_message
        assert result.error_traceback is not None

    def test_partial_execution_on_error(self, config, mock_environment, mock_agent, mock_grader, mock_task):
        """Test partial results saved on error."""
        # Agent works for 2 steps then fails
        mock_agent.step.side_effect = [
            Action(action_type="left_click", params={"coordinate": [100, 200]}),
            ValueError("Agent crashed"),
        ]

        orchestrator = Orchestrator(config, mock_environment, mock_agent)
        result = orchestrator.run_task(mock_task)

        assert result.execution_status == "agent_error"
        assert result.agent_steps == 2  # Completed 1 step, error on step 2
