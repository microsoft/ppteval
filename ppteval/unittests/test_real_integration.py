"""
Real integration test for ppteval - tests with actual ScreenEnv and real tasks.

This test file contains integration tests that spin up actual ScreenEnv instances
with real Office files and tasks from the task registry.
"""

import os
import json
import pytest
from pathlib import Path
from dotenv import load_dotenv

from ppteval import Orchestrator, OrchestratorConfig
from ppteval.agents import CUAAgent, UITARSAgent
from ppteval.core.task import Task
from ppteval.graders.ppt_grader import PPTGrader
from ppteval.environments import ScreenEnvEnvironment
from ppteval.config import EnvironmentConfig

# Load environment variables
load_dotenv()


@pytest.fixture
def workspace_root():
    """Get the workspace root directory."""
    return Path(__file__).parent.parent.parent


@pytest.fixture
def task_registry_path(workspace_root):
    """Get the task registry path."""
    return workspace_root / "task_registry" / "tasks.json"


@pytest.fixture
def simple_ppt_task(workspace_root, task_registry_path):
    """
    Load a simple PowerPoint task from the registry.

    Uses task 3-002: "Change the lecture number from 'Lecture 3' to 'Lecture 1'"
    This is an Easy difficulty task.
    """
    # Load task registry
    with open(task_registry_path, 'r') as f:
        tasks = json.load(f)

    # Get task 3-002 (easy task)
    task_id = "3-002"
    task_data = tasks[task_id]

    # Create Task object
    task = Task(
        task_id=task_id,
        goal=task_data["goal"],
        input_file_path=workspace_root / task_data["file_path"],
        grader=PPTGrader(rubric_path=workspace_root / task_data["rubric_path"]),
        tags=task_data.get("tags", []),
        metadata=task_data.get("misc", {})
    )

    return task


@pytest.fixture
def orchestrator_config(tmp_path):
    """Create orchestrator config with temporary results directory."""
    return OrchestratorConfig(
        results_dir=tmp_path / "results",
        max_steps=15,  # Limit steps for testing
        save_screenshots=True,
        screenshot_interval=1  # Save every step for debugging
    )


@pytest.fixture
def environment_config():
    """Create environment configuration."""
    return EnvironmentConfig(
        headless=True,  # Run in headless mode for CI
        resolution=(1024, 768),  # Standard resolution for CUA, UITARS, Claude
        step_delay=1.0,
        max_retries=3,
        onedrive_root="/PPTEval"
    )


@pytest.mark.slow
@pytest.mark.integration
class TestRealIntegrationCUA:
    """
    Real integration tests with CUA agent and ScreenEnv.

    These tests require:
    - CLIENT_ID environment variable
    - CUA_BASE_URL environment variable
    - Active internet connection
    - OneDrive access
    """

    def test_cua_agent_with_real_task(
        self,
        simple_ppt_task,
        environment_config,
        orchestrator_config
    ):
        """
        Test CUA agent with a real PowerPoint task using ScreenEnv.

        This test:
        1. Creates a real ScreenEnv environment
        2. Opens an actual PowerPoint file from OneDrive
        3. Runs CUA agent to complete a simple task
        4. Grades the result using PPTGrader
        5. Verifies all files are saved correctly
        """
        # Skip if no environment variables
        if not os.getenv("CLIENT_ID") or not os.getenv("CUA_BASE_URL"):
            pytest.skip("CLIENT_ID or CUA_BASE_URL not set")

        print(f"\n{'='*80}")
        print(f"REAL INTEGRATION TEST: CUA Agent with ScreenEnv")
        print(f"{'='*80}")
        print(f"Task ID: {simple_ppt_task.task_id}")
        print(f"Goal: {simple_ppt_task.goal}")
        print(f"File: {simple_ppt_task.input_file_path}")
        print(f"{'='*80}\n")

        # Create ScreenEnv environment
        environment = ScreenEnvEnvironment(
            task=simple_ppt_task,
            config=environment_config,
            client_id=os.getenv("CLIENT_ID")
        )

        # Create CUA agent with Azure configuration
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

        # Create orchestrator
        orchestrator = Orchestrator(
            config=orchestrator_config,
            environment=environment,
            agent=agent
        )

        try:
            print("\n[Test] Starting task execution...")

            # Run the task
            result = orchestrator.run_task(simple_ppt_task)

            print(f"\n[Test] Task completed!")
            print(f"  - Success: {result.success}")
            print(f"  - Agent steps: {result.agent_steps}")
            print(f"  - Execution time: {result.execution_time_seconds:.2f}s")

            if result.evaluation_result:
                print(f"  - Evaluation score: {result.evaluation_result.score:.2f}")
                print(f"  - Evaluation success: {result.evaluation_result.success}")

            # Verify result structure
            assert result is not None, "Result should not be None"
            assert result.task_id == simple_ppt_task.task_id
            assert isinstance(result.success, bool)
            assert isinstance(result.agent_steps, int)
            assert result.agent_steps > 0, "Agent should have taken at least one step"

            # Verify evaluation was performed
            assert result.evaluation_result is not None, "Evaluation should have been performed"
            assert hasattr(result.evaluation_result, 'score')
            assert hasattr(result.evaluation_result, 'success')

            # Verify files were created
            task_dir = result.screenshots_dir.parent if result.screenshots_dir else None
            if task_dir:
                actions_file = task_dir / "actions.json"
                timing_file = task_dir / "timing.json"
                result_file = task_dir / "result.json"

                assert actions_file.exists(), f"Actions file should exist: {actions_file}"
                assert timing_file.exists(), f"Timing file should exist: {timing_file}"
                assert result_file.exists(), f"Result file should exist: {result_file}"

                print(f"\n[Test] Result files created:")
                print(f"  - Actions: {actions_file}")
                print(f"  - Timing: {timing_file}")
                print(f"  - Result: {result_file}")
                print(f"  - Screenshots: {result.screenshots_dir}")

            print(f"\n{'='*80}")
            print(f"TEST PASSED: CUA agent completed real task successfully!")
            print(f"{'='*80}\n")

        finally:
            # Clean up
            agent.close()
            environment.close()


@pytest.mark.slow
@pytest.mark.integration
class TestRealIntegrationUITARS:
    """
    Real integration tests with UITARS agent and ScreenEnv.

    These tests require:
    - CLIENT_ID environment variable
    - UITARS_TOKEN environment variable
    - UITARS_ENDPOINT_URL environment variable
    - Active internet connection
    - OneDrive access
    """

    def test_uitars_agent_with_real_task(
        self,
        simple_ppt_task,
        environment_config,
        orchestrator_config
    ):
        """
        Test UITARS agent with a real PowerPoint task using ScreenEnv.
        """
        # Skip if no environment variables
        if not os.getenv("CLIENT_ID") or not os.getenv("UITARS_TOKEN"):
            pytest.skip("CLIENT_ID or UITARS_TOKEN not set")

        print(f"\n{'='*80}")
        print(f"REAL INTEGRATION TEST: UITARS Agent with ScreenEnv")
        print(f"{'='*80}")
        print(f"Task ID: {simple_ppt_task.task_id}")
        print(f"Goal: {simple_ppt_task.goal}")
        print(f"File: {simple_ppt_task.input_file_path}")
        print(f"{'='*80}\n")

        # Create ScreenEnv environment
        environment = ScreenEnvEnvironment(
            task=simple_ppt_task,
            config=environment_config,
            client_id=os.getenv("CLIENT_ID")
        )

        # Create UITARS agent
        uitars_config = {
            "model_name": "uitars-v1",
            "endpoint_url": os.getenv("UITARS_ENDPOINT_URL"),
            "token": os.getenv("UITARS_TOKEN"),
            "display_size": {"width": 1024, "height": 768},
            "temperature": 0.7,
        }
        agent = UITARSAgent(config=uitars_config)

        # Create orchestrator
        orchestrator = Orchestrator(
            config=orchestrator_config,
            environment=environment,
            agent=agent
        )

        try:
            print("\n[Test] Starting task execution...")

            # Run the task
            result = orchestrator.run_task(simple_ppt_task)

            print(f"\n[Test] Task completed!")
            print(f"  - Success: {result.success}")
            print(f"  - Agent steps: {result.agent_steps}")
            print(f"  - Execution time: {result.execution_time_seconds:.2f}s")

            if result.evaluation_result:
                print(f"  - Evaluation score: {result.evaluation_result.score:.2f}")
                print(f"  - Evaluation success: {result.evaluation_result.success}")

            # Verify result structure
            assert result is not None
            assert result.task_id == simple_ppt_task.task_id
            assert isinstance(result.success, bool)
            assert isinstance(result.agent_steps, int)
            assert result.agent_steps > 0

            print(f"\n{'='*80}")
            print(f"TEST PASSED: UITARS agent completed real task successfully!")
            print(f"{'='*80}\n")

        finally:
            # Clean up
            agent.close()
            environment.close()


if __name__ == "__main__":
    """
    Run this test directly with:
    python -m pytest ppteval/unittests/test_real_integration.py -v -s -m "slow and integration"

    Or run just CUA test:
    python -m pytest ppteval/unittests/test_real_integration.py::TestRealIntegrationCUA::test_cua_agent_with_real_task -v -s
    """
    pytest.main([__file__, "-v", "-s", "-m", "slow and integration"])
