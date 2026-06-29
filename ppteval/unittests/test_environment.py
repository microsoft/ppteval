"""
Unit tests for ScreenEnvEnvironment.

Tests setup, update, cleanup, and download_artifacts methods with comprehensive
mocking to avoid real OneDrive/sandbox dependencies.
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call
import pytest

from ppteval.core.base import Action, GUIState
from ppteval.core.task import Task
from ppteval.config import EnvironmentConfig
from ppteval.environments.screenenv_environment import ScreenEnvEnvironment


@pytest.fixture
def mock_task(tmp_path):
    """Create a mock task with a temporary input file."""
    input_file = tmp_path / "test.pptx"
    input_file.write_text("mock powerpoint content")

    return Task(
        task_id="test-task-001",
        goal="Test goal",
        input_file_path=input_file,
        grader=None,
        tags=["test"],
        metadata={}
    )


@pytest.fixture
def mock_config():
    """Create a mock environment configuration."""
    return EnvironmentConfig(
        headless=True,
        resolution="1920x1080",
        step_delay=0.5,
        max_retries=2,
        onedrive_root="test_root"
    )


@pytest.fixture
def mock_onedrive_client():
    """Create a mock OneDrive client."""
    client = Mock()
    client.upload_file = Mock(return_value=None)
    client.get_edit_link = Mock(return_value="https://1drv.ms/fake_edit_link")
    client.download_file = Mock(return_value=None)
    return client


@pytest.fixture
def mock_sandbox():
    """Create a mock screenenv sandbox."""
    sandbox = Mock()

    # Mock chromium_context with pages and frames
    mock_page = Mock()
    mock_frame = Mock()
    mock_frame.name = "WacFrame_Edit_0"
    mock_page.frames = [mock_frame]
    mock_page.reload = Mock()

    mock_context = Mock()
    mock_context.pages = [mock_page]

    sandbox.chromium_context = mock_context
    sandbox.open = Mock()
    sandbox.left_click = Mock()
    sandbox.right_click = Mock()
    sandbox.middle_click = Mock()
    sandbox.write = Mock()
    sandbox.press = Mock()
    sandbox.move_mouse = Mock()
    sandbox.scroll = Mock()
    sandbox.wait = Mock()
    sandbox.drag = Mock()
    sandbox.screenshot = Mock(return_value=b"fake_screenshot_bytes")
    sandbox.desktop_screenshot = Mock(return_value=b"fake_screenshot_bytes")
    sandbox.close = Mock()

    return sandbox


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    logger = Mock()
    logger.log_info = Mock()
    logger.log_error = Mock()
    logger.log_action = Mock()
    logger.log_state = Mock()
    return logger


class TestScreenEnvEnvironmentInit:
    """Test ScreenEnvEnvironment initialization."""

    def test_init_with_explicit_client_id(self, mock_task, mock_config):
        """Test initialization with explicit client ID."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.return_value = Mock()

            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-client-id")

            assert env.task == mock_task
            assert env.config == mock_config
            assert env.client_id == "test-client-id"
            assert env.sandbox is None
            assert env.remote_file_path is None
            assert env.edit_link is None
            assert env.current_step == 0

            MockClient.assert_called_once_with(
                client_id="test-client-id",
                root_path="test_root"
            )

    def test_init_with_env_var_client_id(self, mock_task, mock_config, monkeypatch):
        """Test initialization with CLIENT_ID from environment variable."""
        monkeypatch.setenv("CLIENT_ID", "env-client-id")

        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.return_value = Mock()

            env = ScreenEnvEnvironment(mock_task, mock_config)

            assert env.client_id == "env-client-id"

            MockClient.assert_called_once_with(
                client_id="env-client-id",
                root_path="test_root"
            )

    def test_init_without_client_id_raises_error(self, mock_task, mock_config, monkeypatch):
        """Test that missing CLIENT_ID raises ValueError."""
        monkeypatch.delenv("CLIENT_ID", raising=False)

        with pytest.raises(ValueError, match="CLIENT_ID must be provided"):
            ScreenEnvEnvironment(mock_task, mock_config)

    def test_init_onedrive_failure_raises_infrastructure_error(self, mock_task, mock_config):
        """Test that OneDrive client initialization failure raises proper error."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.side_effect = Exception("OneDrive auth failed")

            with pytest.raises(ValueError, match="Failed to initialize OneDrive client.*infrastructure failure"):
                ScreenEnvEnvironment(mock_task, mock_config, client_id="test-client-id")


class TestScreenEnvEnvironmentWacFrame:
    """Test WacFrame detection methods."""

    def test_check_wacframe_available_success(self, mock_task, mock_config, mock_sandbox):
        """Test successful WacFrame detection."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox

            result = env._check_wacframe_available()

            assert result is True

    def test_check_wacframe_no_sandbox(self, mock_task, mock_config):
        """Test WacFrame check with no sandbox."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")

            result = env._check_wacframe_available()

            assert result is False

    def test_check_wacframe_no_chromium_context(self, mock_task, mock_config):
        """Test WacFrame check with no chromium context."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = Mock()
            env.sandbox.chromium_context = None

            result = env._check_wacframe_available()

            assert result is False

    def test_check_wacframe_no_pages(self, mock_task, mock_config):
        """Test WacFrame check with no pages."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = Mock()
            env.sandbox.chromium_context = Mock()
            env.sandbox.chromium_context.pages = []

            result = env._check_wacframe_available()

            assert result is False

    def test_check_wacframe_not_found(self, mock_task, mock_config):
        """Test WacFrame check when frame not found."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")

            mock_sandbox = Mock()
            mock_page = Mock()
            mock_frame = Mock()
            mock_frame.name = "SomeOtherFrame"
            mock_page.frames = [mock_frame]

            mock_context = Mock()
            mock_context.pages = [mock_page]
            mock_sandbox.chromium_context = mock_context

            env.sandbox = mock_sandbox

            result = env._check_wacframe_available()

            assert result is False

    @patch('time.sleep')  # Speed up test by mocking sleep
    def test_wait_for_office_online_ready_immediate_success(
        self, mock_sleep, mock_task, mock_config, mock_sandbox
    ):
        """Test immediate Office Online readiness."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = Mock()

            env._wait_for_office_online_ready(max_retries=2, wait_timeout=5)

            # Should succeed on first attempt after initial wait
            assert mock_sleep.called

    @patch('time.sleep')
    @patch('time.time')
    def test_wait_for_office_online_ready_after_retry(
        self, mock_time, mock_sleep, mock_task, mock_config
    ):
        """Test Office Online readiness after page refresh."""
        # Simulate time progression
        mock_time.side_effect = [0, 1, 2, 3, 11]  # Timeout on first attempt

        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")

            # First attempt: no WacFrame, second attempt: WacFrame found
            mock_sandbox = Mock()
            mock_page = Mock()
            mock_page.reload = Mock()

            # First check: no WacFrame
            mock_frame_1 = Mock()
            mock_frame_1.name = "OtherFrame"

            # Second check: WacFrame present
            mock_frame_2 = Mock()
            mock_frame_2.name = "WacFrame_Edit_0"

            # Set up frames to change after reload
            mock_page.frames = [mock_frame_1]

            mock_context = Mock()
            mock_context.pages = [mock_page]
            mock_sandbox.chromium_context = mock_context

            env.sandbox = mock_sandbox

            # This will timeout on first attempt but should continue
            env._wait_for_office_online_ready(max_retries=2, wait_timeout=10)

            # Should have called reload
            assert mock_page.reload.called


class TestScreenEnvEnvironmentSetup:
    """Test ScreenEnvEnvironment setup method."""

    @patch('ppteval.environments.screenenv_environment.Sandbox')
    @patch('time.time')
    @patch('time.sleep')
    def test_setup_success(
        self, mock_sleep, mock_time, MockSandbox,
        mock_task, mock_config, mock_onedrive_client, mock_sandbox, mock_logger
    ):
        """Test successful environment setup."""
        mock_time.return_value = 1234567890
        MockSandbox.return_value = mock_sandbox

        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.return_value = mock_onedrive_client

            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.logger = mock_logger

            # Mock ribbon setup.
            with patch('ppteval.utils.powerpoint.ensure_classic_ribbon_always_show'):
                state = env.setup()

            # Verify OneDrive upload
            mock_onedrive_client.upload_file.assert_called_once()
            call_args = mock_onedrive_client.upload_file.call_args
            assert "tasks/test-task-001_1234567890.pptx" in str(call_args)

            # Verify edit link retrieval
            mock_onedrive_client.get_edit_link.assert_called_once()

            # Verify sandbox creation (resolution passed as string from config)
            MockSandbox.assert_called_once_with(
                headless=True,
                resolution='1920x1080'
            )

            # Verify edit link opened
            mock_sandbox.open.assert_called_once_with("https://1drv.ms/fake_edit_link")

            # Verify returned state
            assert isinstance(state, GUIState)
            assert state.screenshot == b"fake_screenshot_bytes"

            # Verify environment state
            assert env.remote_file_path == "tasks/test-task-001_1234567890.pptx"
            assert env.edit_link == "https://1drv.ms/fake_edit_link"
            assert env.sandbox == mock_sandbox

    @patch('time.time')
    def test_setup_upload_failure_infrastructure(
        self, mock_time, mock_task, mock_config, mock_onedrive_client, mock_logger
    ):
        """Test setup with OneDrive upload failure (infrastructure)."""
        mock_time.return_value = 1234567890
        mock_onedrive_client.upload_file.side_effect = Exception("Rate limited")

        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.return_value = mock_onedrive_client

            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.logger = mock_logger

            with pytest.raises(Exception, match="Rate limited"):
                env.setup()

    @patch('ppteval.environments.screenenv_environment.Sandbox')
    @patch('time.time')
    def test_setup_sandbox_creation_failure(
        self, mock_time, MockSandbox,
        mock_task, mock_config, mock_onedrive_client, mock_logger
    ):
        """Test setup with sandbox creation failure."""
        mock_time.return_value = 1234567890
        MockSandbox.side_effect = Exception("Sandbox unavailable")

        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.return_value = mock_onedrive_client

            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.logger = mock_logger

            with pytest.raises(Exception, match="Sandbox unavailable"):
                env.setup()


class TestScreenEnvEnvironmentUpdate:
    """Test ScreenEnvEnvironment update method."""

    @patch('time.sleep')
    def test_update_terminal_action_finish(
        self, mock_sleep, mock_task, mock_config, mock_sandbox, mock_logger
    ):
        """Test update with terminal 'finish' action."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger

            action = Action(action_type="finish", params={}, reasoning="Task complete")
            state = env.update(action)

            # Verify terminal action logged
            mock_logger.log_info.assert_called()

            # Verify screenshot returned
            assert isinstance(state, GUIState)
            assert state.screenshot == b"fake_screenshot_bytes"
            assert state.done is True

    @patch('time.sleep')
    def test_update_terminal_action_give_up(
        self, mock_sleep, mock_task, mock_config, mock_sandbox, mock_logger
    ):
        """Test update with terminal 'give_up' action."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger

            action = Action(action_type="give_up", params={}, reasoning="Cannot complete")
            state = env.update(action)

            # Verify terminal action logged
            mock_logger.log_info.assert_called()

            # Verify screenshot returned
            assert isinstance(state, GUIState)
            assert state.done is True

    @patch('time.sleep')
    def test_update_click_action(
        self, mock_sleep, mock_task, mock_config, mock_sandbox, mock_logger
    ):
        """Test update with click action."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger
            env.current_step = 5

            action = Action(
                action_type="click",
                params={"x": 100, "y": 200, "button": "left"},
                reasoning="Click button"
            )
            state = env.update(action)

            # Verify action executed
            mock_sandbox.left_click.assert_called_once_with(x=100, y=200)

            # Verify step incremented
            assert env.current_step == 6

            # Verify screenshot returned
            assert isinstance(state, GUIState)
            assert state.done is False

            # Verify step delay called
            mock_sleep.assert_called()

    @patch('time.sleep')
    def test_update_type_action(
        self, mock_sleep, mock_task, mock_config, mock_sandbox, mock_logger
    ):
        """Test update with type action."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger

            action = Action(
                action_type="type",
                params={"text": "Hello World"},
                reasoning="Type text"
            )
            state = env.update(action)

            # Verify action executed
            mock_sandbox.write.assert_called_once_with(text="Hello World")

            # Verify screenshot returned
            assert isinstance(state, GUIState)
            assert state.done is False

    @patch('time.sleep')
    def test_update_keypress_action(
        self, mock_sleep, mock_task, mock_config, mock_sandbox, mock_logger
    ):
        """Test update with keypress action."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger

            action = Action(
                action_type="keypress",
                params={"key": "Enter"},
                reasoning="Press Enter"
            )
            state = env.update(action)

            # Verify action executed
            mock_sandbox.press.assert_called_once_with(key="Enter")
            assert state.done is False

    @patch('time.sleep')
    def test_update_scroll_action_down(
        self, mock_sleep, mock_task, mock_config, mock_sandbox, mock_logger
    ):
        """Test update with scroll down action."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger

            action = Action(
                action_type="scroll",
                params={"direction": "down", "amount": 5},
                reasoning="Scroll down"
            )
            state = env.update(action)

            # Verify scroll executed
            mock_sandbox.scroll.assert_called_once_with(direction="down", amount=5)
            assert state.done is False

    @patch('time.sleep')
    def test_update_scroll_action_up(
        self, mock_sleep, mock_task, mock_config, mock_sandbox, mock_logger
    ):
        """Test update with scroll up action."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger

            action = Action(
                action_type="scroll",
                params={"direction": "up", "amount": 3},
                reasoning="Scroll up"
            )
            state = env.update(action)

            # Verify scroll executed
            mock_sandbox.scroll.assert_called_once_with(direction="up", amount=3)
            assert state.done is False

    @patch('time.sleep')
    def test_update_wait_action(
        self, mock_sleep, mock_task, mock_config, mock_sandbox, mock_logger
    ):
        """Test update with wait action."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger

            action = Action(
                action_type="wait",
                params={"duration": 2.0},
                reasoning="Wait 2 seconds"
            )
            state = env.update(action)

            # Verify wait executed (converted from seconds to milliseconds)
            mock_sandbox.wait.assert_called_once_with(2000)
            assert state.done is False

    @patch('time.sleep')
    def test_update_delegates_to_configured_action_space(
        self, mock_sleep, mock_task, mock_config, mock_sandbox, mock_logger
    ):
        """Test update delegates action execution to the configured action space."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger
            env.action_space = Mock()

            action = Action(action_type="custom_action", params={"value": 1})
            state = env.update(action)

            env.action_space.execute.assert_called_once_with(mock_sandbox, action)
            assert state.done is False

    @patch('time.sleep')
    def test_update_action_execution_error(
        self, mock_sleep, mock_task, mock_config, mock_sandbox, mock_logger
    ):
        """Test update with action execution error (logs error but continues)."""
        mock_sandbox.left_click.side_effect = Exception("Click failed")

        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger

            action = Action(
                action_type="click",
                params={"x": 100, "y": 200, "button": "left"},
                reasoning="Click button"
            )

            # Should not raise - error is logged but execution continues
            state = env.update(action)

            # Verify error logged
            mock_logger.log_error.assert_called()

            # Still returns a state
            assert isinstance(state, GUIState)
            assert state.done is False


class TestScreenEnvEnvironmentCleanup:
    """Test ScreenEnvEnvironment cleanup method."""

    def test_cleanup_success(self, mock_task, mock_config, mock_sandbox, mock_logger):
        """Test successful cleanup."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger

            env.cleanup()

            # Verify sandbox closed
            mock_sandbox.close.assert_called_once()

    def test_cleanup_no_sandbox(self, mock_task, mock_config, mock_logger):
        """Test cleanup with no sandbox."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.logger = mock_logger

            # Should not raise error
            env.cleanup()

    def test_cleanup_with_error(self, mock_task, mock_config, mock_sandbox, mock_logger):
        """Test cleanup with sandbox close error."""
        mock_sandbox.close.side_effect = Exception("Close failed")

        with patch('ppteval.environments.screenenv_environment.OneDriveClient'):
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.sandbox = mock_sandbox
            env.logger = mock_logger

            # Should not raise error (graceful degradation)
            env.cleanup()

            # Verify error logged
            mock_logger.log_error.assert_called()


class TestScreenEnvEnvironmentDownloadArtifacts:
    """Test ScreenEnvEnvironment download_artifacts method."""

    @patch('ppteval.environments.screenenv_environment.download_powerpoint_as_images_sync')
    def test_download_artifacts_success(
        self, mock_download_images, mock_task, mock_config,
        mock_onedrive_client, mock_logger, tmp_path
    ):
        """Test successful artifact download."""
        # Setup mock return values
        modified_file = tmp_path / "modified.pptx"
        modified_file.write_text("modified content")
        mock_onedrive_client.download_file.return_value = modified_file

        image_dir = tmp_path / "images"
        image_dir.mkdir()
        (image_dir / "slide_1.png").write_text("image1")
        mock_download_images.return_value = image_dir

        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.return_value = mock_onedrive_client

            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.remote_file_path = "tasks/test_file.pptx"
            env.edit_link = "https://1drv.ms/fake_link"
            env.logger = mock_logger

            artifacts = env.download_artifacts()

            # Verify download called (with download directory)
            assert mock_onedrive_client.download_file.called
            call_args = mock_onedrive_client.download_file.call_args
            assert call_args[0][0] == "tasks/test_file.pptx"
            assert "ppteval_test-task-001_" in call_args[0][1]

            # Verify image generation called
            assert mock_download_images.called
            call_kwargs = mock_download_images.call_args[1]
            assert call_kwargs['edit_link'] == "https://1drv.ms/fake_link"

            # Verify artifacts returned
            assert "file" in artifacts
            assert "images" in artifacts
            assert "original_file" in artifacts
            assert artifacts["file"] == modified_file
            assert artifacts["images"] == image_dir
            assert artifacts["original_file"] == mock_task.input_file_path

    def test_download_artifacts_no_remote_path(
        self, mock_task, mock_config, mock_onedrive_client, mock_logger
    ):
        """Test download artifacts with no remote file path (returns empty artifacts)."""
        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.return_value = mock_onedrive_client

            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.remote_file_path = None
            env.logger = mock_logger

            artifacts = env.download_artifacts()

            # Should return empty artifacts, not raise error
            assert artifacts == {}
            mock_logger.log_error.assert_called_once()

    def test_download_artifacts_download_failure(
        self, mock_task, mock_config, mock_onedrive_client, mock_logger
    ):
        """Test download artifacts with download failure (returns partial artifacts)."""
        mock_onedrive_client.download_file.side_effect = Exception("Download failed")

        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.return_value = mock_onedrive_client

            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.remote_file_path = "tasks/test_file.pptx"
            env.edit_link = "https://1drv.ms/fake_link"
            env.logger = mock_logger

            artifacts = env.download_artifacts()

            # Should return partial artifacts, not raise error
            assert "file" not in artifacts  # Download failed

            # Verify error logged
            assert any("Failed to download file" in str(call) for call in mock_logger.log_error.call_args_list)

    @patch('ppteval.environments.screenenv_environment.download_powerpoint_as_images_sync')
    def test_download_artifacts_image_generation_failure(
        self, mock_download_images, mock_task, mock_config,
        mock_onedrive_client, mock_logger, tmp_path
    ):
        """Test download artifacts with image generation failure (returns partial artifacts)."""
        modified_file = tmp_path / "modified.pptx"
        modified_file.write_text("modified content")
        mock_onedrive_client.download_file.return_value = modified_file

        mock_download_images.side_effect = Exception("Image generation failed")

        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.return_value = mock_onedrive_client

            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.remote_file_path = "tasks/test_file.pptx"
            env.edit_link = "https://1drv.ms/fake_link"
            env.logger = mock_logger

            artifacts = env.download_artifacts()

            # Should return partial artifacts (file but no images)
            assert "file" in artifacts
            assert "images" not in artifacts or artifacts["images"] is None

            # Verify error logged
            assert any("Failed to generate slide images" in str(call) for call in mock_logger.log_error.call_args_list)


class TestScreenEnvEnvironmentIntegration:
    """Integration tests for ScreenEnvEnvironment (with mocking)."""

    @patch('ppteval.utils.powerpoint.ensure_classic_ribbon_always_show')
    @patch('ppteval.environments.screenenv_environment.download_powerpoint_as_images_sync')
    @patch('ppteval.environments.screenenv_environment.Sandbox')
    @patch('time.time')
    @patch('time.sleep')
    def test_full_workflow(
        self, mock_sleep, mock_time, MockSandbox, mock_download_images,
        mock_ribbon, mock_task, mock_config, mock_onedrive_client, tmp_path
    ):
        """Test full workflow: setup -> update -> cleanup -> download."""
        # Setup mocks
        mock_time.return_value = 1234567890

        mock_sandbox = Mock()
        mock_page = Mock()
        mock_frame = Mock()
        mock_frame.name = "WacFrame_Edit_0"
        mock_page.frames = [mock_frame]
        mock_page.reload = Mock()

        mock_context = Mock()
        mock_context.pages = [mock_page]
        mock_sandbox.chromium_context = mock_context
        mock_sandbox.open = Mock()
        mock_sandbox.left_click = Mock()
        mock_sandbox.screenshot = Mock(return_value=b"screenshot")
        mock_sandbox.desktop_screenshot = Mock(return_value=b"screenshot")
        mock_sandbox.close = Mock()

        MockSandbox.return_value = mock_sandbox

        modified_file = tmp_path / "modified.pptx"
        modified_file.write_text("modified")
        mock_onedrive_client.download_file.return_value = modified_file

        image_dir = tmp_path / "images"
        image_dir.mkdir()
        mock_download_images.return_value = image_dir

        with patch('ppteval.environments.screenenv_environment.OneDriveClient') as MockClient:
            MockClient.return_value = mock_onedrive_client

            # Create environment
            env = ScreenEnvEnvironment(mock_task, mock_config, client_id="test-id")
            env.logger = Mock()

            # 1. Setup
            state1 = env.setup()
            assert isinstance(state1, GUIState)
            assert env.sandbox is not None
            assert env.remote_file_path == "tasks/test-task-001_1234567890.pptx"

            # 2. Execute action
            action = Action(action_type="click", params={"x": 100, "y": 200, "button": "left"}, reasoning="Click")
            state2 = env.update(action)
            assert isinstance(state2, GUIState)
            assert state2.done is False
            mock_sandbox.left_click.assert_called_once()

            # 3. Terminal action
            action_finish = Action(action_type="finish", params={}, reasoning="Done")
            state3 = env.update(action_finish)
            assert isinstance(state3, GUIState)
            assert state3.done is True

            # 4. Cleanup
            env.cleanup()
            mock_sandbox.close.assert_called_once()

            # 5. Download artifacts
            artifacts = env.download_artifacts()
            assert "file" in artifacts
            assert "images" in artifacts
            assert "original_file" in artifacts
