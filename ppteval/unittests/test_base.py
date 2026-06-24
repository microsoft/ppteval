"""
Unit tests for ppteval core base classes.

Run with: python -m pytest ppteval/unittests/test_base.py
"""

import pytest
from pathlib import Path

from ppteval.core.base import (
    State,
    GUIState,
    ExtendedGUIState,
    APIState,
    Action,
    ActionSpace,
    EvaluationResult,
    TaskResult,
)
from ppteval.action_spaces import CUAActionSpace


class TestState:
    """Tests for State hierarchy"""

    def test_gui_state_creation(self):
        """Test creating a GUIState"""
        screenshot = b"fake_screenshot_data"
        state = GUIState(screenshot=screenshot, done=False)

        assert state.screenshot == screenshot
        assert state.done == False
        assert isinstance(state, State)

    def test_extended_gui_state(self):
        """Test ExtendedGUIState with additional context"""
        screenshot = b"fake_screenshot_data"
        accessibility_tree = {"type": "window", "children": []}
        dom = {"html": "<html></html>"}

        state = ExtendedGUIState(
            screenshot=screenshot,
            done=False,
            accessibility_tree=accessibility_tree,
            dom=dom
        )

        assert state.screenshot == screenshot
        assert state.accessibility_tree == accessibility_tree
        assert state.dom == dom
        assert isinstance(state, GUIState)

    def test_api_state_creation(self):
        """Test creating an APIState"""
        workspace = Path("/tmp/workspace")
        files = [Path("file1.py"), Path("file2.py")]

        state = APIState(
            done=False,
            workspace_path=workspace,
            available_files=files,
            last_operation_result={"status": "success"}
        )

        assert state.workspace_path == workspace
        assert len(state.available_files) == 2
        assert state.last_operation_result["status"] == "success"
        assert isinstance(state, State)


class TestAction:
    """Tests for Action class"""

    def test_action_creation(self):
        """Test creating an Action"""
        action = Action(
            action_type="click",
            params={"x": 100, "y": 200},
            reasoning="Clicking the button"
        )

        assert action.action_type == "click"
        assert action.params["x"] == 100
        assert action.params["y"] == 200
        assert action.reasoning == "Clicking the button"

    def test_action_without_reasoning(self):
        """Test creating Action without reasoning"""
        action = Action(
            action_type="type",
            params={"text": "hello"}
        )

        assert action.action_type == "type"
        assert action.reasoning is None

    def test_is_terminal_finish(self):
        """Test is_terminal for finish action"""
        action = Action(action_type="finish", params={})
        assert action.is_terminal() == True

    def test_is_terminal_give_up(self):
        """Test is_terminal for give_up action"""
        action = Action(action_type="give_up", params={})
        assert action.is_terminal() == True

    def test_is_terminal_non_terminal(self):
        """Test is_terminal for non-terminal actions"""
        action = Action(action_type="click", params={"x": 0, "y": 0})
        assert action.is_terminal() == False


class TestActionSpace:
    """Tests for agent action space abstractions."""

    def test_cua_action_space_implements_action_space(self):
        action_space = CUAActionSpace()
        assert isinstance(action_space, ActionSpace)


class TestEvaluationResult:
    """Tests for EvaluationResult"""

    def test_evaluation_result_success(self):
        """Test successful evaluation result"""
        result = EvaluationResult(
            score=0.95,
            success=True,
            reason="All criteria met",
            details={"critical": 1.0, "non_critical": 0.9}
        )

        assert result.score == 0.95
        assert result.success == True
        assert result.reason == "All criteria met"
        assert result.details["critical"] == 1.0

    def test_evaluation_result_failure(self):
        """Test failed evaluation result"""
        result = EvaluationResult(
            score=0.3,
            success=False,
            reason="Missing required elements"
        )

        assert result.score == 0.3
        assert result.success == False
        assert len(result.details) == 0


class TestTaskResult:
    """Tests for TaskResult"""

    def test_task_result_creation(self):
        """Test creating a TaskResult"""
        eval_result = EvaluationResult(
            score=0.85,
            success=True,
            reason="Task completed successfully"
        )

        result = TaskResult(
            task_id="test-001",
            goal="Test task",
            success=True,
            score=0.85,
            execution_status="success",
            agent_steps=10,
            execution_time_seconds=45.5,
            verification_status="success",
            evaluation_result=eval_result,
            screenshots_dir=Path("/tmp/screenshots"),
            final_file_path=Path("/tmp/output.pptx")
        )

        assert result.task_id == "test-001"
        assert result.success == True
        assert result.score == 0.85
        assert result.agent_steps == 10
        assert result.evaluation_result.score == 0.85

    def test_task_result_to_dict(self):
        """Test TaskResult serialization to dict"""
        eval_result = EvaluationResult(
            score=0.75,
            success=True,
            reason="Good",
            details={"key": "value"}
        )

        result = TaskResult(
            task_id="test-002",
            goal="Another test",
            success=True,
            score=0.75,
            execution_status="success",
            agent_steps=5,
            execution_time_seconds=20.0,
            verification_status="success",
            evaluation_result=eval_result
        )

        result_dict = result.to_dict()

        assert result_dict["task_id"] == "test-002"
        assert result_dict["score"] == 0.75
        assert result_dict["agent_steps"] == 5
        assert "evaluation_details" in result_dict
        assert result_dict["evaluation_details"]["score"] == 0.75
        assert result_dict["evaluation_details"]["success"] == True

    def test_task_result_to_dict_no_evaluation(self):
        """Test TaskResult serialization without evaluation"""
        result = TaskResult(
            task_id="test-003",
            goal="Failed task",
            success=False,
            score=None,
            execution_status="agent_error",
            agent_steps=3,
            execution_time_seconds=10.0,
            verification_status="not_run",
            error_message="Agent crashed"
        )

        result_dict = result.to_dict()

        assert result_dict["task_id"] == "test-003"
        assert result_dict["success"] == False
        assert result_dict["score"] is None
        assert "evaluation_details" not in result_dict
        assert result_dict["error_message"] == "Agent crashed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
