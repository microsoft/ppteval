"""
ScreenEnv-based environment for PowerPoint task execution.

This environment uses screenenv sandbox with OneDrive and PowerPoint Online
to execute GUI-based tasks.
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from screenenv import Sandbox

from ppteval.core.base import Environment, Action, GUIState
from ppteval.action_spaces.screenenv import BaseScreenEnvActionSpace
from ppteval.core.task import Task
from ppteval.config import EnvironmentConfig
from ppteval.utils.onedrive import OneDriveClient
from ppteval.utils.powerpoint import (
    download_powerpoint_as_images_sync,
    download_powerpoint_as_pptx_sync,
)


class ScreenEnvEnvironment(Environment):
    """
    PowerPoint environment using screenenv sandbox + OneDrive.
    """

    def __init__(self, task: Task, config: EnvironmentConfig, client_id: str | None = None):
        """
        Initialize ScreenEnv environment.

        Args:
            task: Task to execute
            config: Environment configuration
            client_id: OneDrive client ID (uses env var CLIENT_ID if None)
        """
        self.task = task
        self.config = config
        self.client_id = client_id or os.getenv("CLIENT_ID")

        if not self.client_id:
            raise ValueError("CLIENT_ID must be provided or set in environment variables")

        # Initialize OneDrive client.
        try:
            self.onedrive_client = OneDriveClient(
                client_id=self.client_id,
                root_path=config.onedrive_root
            )
        except Exception as e:
            raise ValueError(f"Failed to initialize OneDrive client (infrastructure failure): {e}")

        # State
        self.sandbox: Sandbox | None = None
        self.remote_file_path: str | None = None
        self.local_file_name: str | None = None
        self.edit_link: str | None = None
        self.current_step = 0
        self.action_space = BaseScreenEnvActionSpace()

        # Directory management
        self.working_dir: Path | None = None  # Temp dir for operations
        self.result_dir: Path | None = None   # Final dir for artifacts (set by orchestrator)

        # Logger will be injected by orchestrator
        self.logger: Any | None = None

    def _check_wacframe_available(self) -> bool:
        """
        Check if WacFrame is available (Office Online loaded).
        """
        try:
            if not hasattr(self.sandbox, 'chromium_context') or not self.sandbox.chromium_context:
                return False

            context = self.sandbox.chromium_context
            if not context.pages:
                return False

            page = context.pages[0]

            # Check frames
            for f in page.frames:
                try:
                    name = getattr(f, "name", lambda: "")()
                except Exception:
                    try:
                        name = f.name
                    except Exception:
                        name = ""

                if "WacFrame" in str(name):
                    return True

            return False

        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Error checking WacFrame: {e}")
            return False

    def _wait_for_office_online_ready(self, max_retries: int = 3, wait_timeout: int = 10) -> None:
        """
        Wait for Office Online to be ready by checking for WacFrame.
        """
        for attempt in range(max_retries + 1):
            try:
                initial_wait = 5 if attempt == 0 else 3
                time.sleep(initial_wait)

                start_time = time.time()
                while time.time() - start_time < wait_timeout:
                    try:
                        if not hasattr(self.sandbox, 'chromium_context') or not self.sandbox.chromium_context:
                            time.sleep(1)
                            continue

                        context = self.sandbox.chromium_context
                        if not context.pages:
                            time.sleep(1)
                            continue

                        page = context.pages[0]

                        # Check frames
                        wac_frames = []
                        for f in page.frames:
                            try:
                                name = getattr(f, "name", lambda: "")()
                            except Exception:
                                try:
                                    name = f.name
                                except Exception:
                                    name = ""

                            if "WacFrame" in str(name):
                                wac_frames.append(f)

                        if wac_frames:
                            message = f"[ScreenEnv] [ok] Office Online ready (WacFrame detected on attempt {attempt + 1})"
                            print(message)
                            if self.logger:
                                self.logger.log_info(message)
                            return

                    except Exception:
                        pass

                    time.sleep(1)

                # WacFrame not found, retry
                if attempt < max_retries:
                    message = f"[ScreenEnv] [warn] Office Online not ready (attempt {attempt + 1}), refreshing..."
                    print(message)
                    if self.logger:
                        self.logger.log_info(message)

                    try:
                        if hasattr(self.sandbox, 'chromium_context') and self.sandbox.chromium_context:
                            context = self.sandbox.chromium_context
                            if context.pages:
                                page = context.pages[0]
                                page.reload()
                    except Exception as e:
                        print(f"[ScreenEnv] Failed to refresh page: {e}")
                else:
                    message = f"[ScreenEnv] [warn] Office Online may not be fully ready after {max_retries} retries, continuing anyway"
                    print(message)
                    if self.logger:
                        self.logger.log_info(message)

            except Exception as e:
                error_msg = f"Error checking Office Online readiness: {e}"
                if self.logger:
                    self.logger.log_error(error_msg)

                if attempt < max_retries:
                    print(f"[ScreenEnv] Retrying Office Online check (attempt {attempt + 1})")
                    time.sleep(2)
                else:
                    print(f"[ScreenEnv] [warn] {error_msg}, continuing")
                    break

    def setup(self) -> GUIState:
        """
        Setup environment: upload file, create sandbox, open PPT Online.
        """
        try:
            # 1. Upload file to OneDrive with timestamp (avoid locks)
            timestamp = int(time.time())
            file_extension = self.task.input_file_path.suffix
            # Keep OneDrive/Graph paths ASCII-safe and deterministic.
            safe_task_id = re.sub(r"[^A-Za-z0-9._-]+", "_", self.task.task_id).strip("._-")
            if not safe_task_id:
                safe_task_id = "task"
            remote_filename = f"{safe_task_id}_{timestamp}{file_extension}"
            # Keep local artifact name in legacy task_id format for scripts
            # that match files by raw task ID.
            self.local_file_name = f"{self.task.task_id}_{timestamp}{file_extension}"
            self.remote_file_path = f"tasks/{remote_filename}"

            if safe_task_id != self.task.task_id:
                msg = (
                    f"[ScreenEnv] Sanitized task id for OneDrive path: "
                    f"'{self.task.task_id}' -> '{safe_task_id}'"
                )
                print(msg)
                if self.logger:
                    self.logger.log_info(msg)

            print(f"[ScreenEnv] Uploading file to OneDrive: {self.remote_file_path}")
            if self.logger:
                self.logger.log_info(f"Uploading {self.task.input_file_path} to {self.remote_file_path}")

            try:
                self.onedrive_client.upload_file(
                    str(self.task.input_file_path),
                    self.remote_file_path
                )
            except Exception as upload_error:
                # Classify infrastructure errors
                error_str = str(upload_error).lower()
                if "rate" in error_str or "429" in error_str or "throttl" in error_str:
                    error_msg = f"OneDrive rate limit exceeded: {upload_error}"
                elif "network" in error_str or "connection" in error_str or "timeout" in error_str:
                    error_msg = f"Network error during upload: {upload_error}"
                elif "auth" in error_str or "token" in error_str or "401" in error_str or "403" in error_str:
                    error_msg = f"Authentication error during upload: {upload_error}"
                else:
                    error_msg = f"OneDrive upload error: {upload_error}"

                if self.logger:
                    self.logger.log_error(error_msg)
                raise RuntimeError(f"infrastructure failure: {error_msg}")

            # 2. Get edit link
            try:
                self.edit_link = self.onedrive_client.get_edit_link(self.remote_file_path)
            except Exception as link_error:
                error_str = str(link_error).lower()
                if "rate" in error_str or "429" in error_str or "throttl" in error_str:
                    error_msg = f"OneDrive rate limit: {link_error}"
                elif "network" in error_str or "connection" in error_str or "timeout" in error_str:
                    error_msg = f"Network error getting edit link: {link_error}"
                elif "auth" in error_str or "token" in error_str or "401" in error_str or "403" in error_str:
                    error_msg = f"Authentication error getting edit link: {link_error}"
                else:
                    error_msg = f"Failed to get edit link: {link_error}"

                if self.logger:
                    self.logger.log_error(error_msg)
                raise RuntimeError(f"infrastructure failure: {error_msg}")

            if not self.edit_link:
                error_msg = f"No edit link returned for {self.remote_file_path}"
                if self.logger:
                    self.logger.log_error(error_msg)
                raise RuntimeError(f"infrastructure failure: {error_msg}")

            print(f"[ScreenEnv] Edit link: {self.edit_link}")

            # 3. Create sandbox
            sandbox_kwargs = {"headless": self.config.headless}
            if self.config.resolution:
                sandbox_kwargs["resolution"] = self.config.resolution

            try:
                self.sandbox = Sandbox(**sandbox_kwargs)
            except Exception as sandbox_error:
                error_msg = f"Failed to initialize sandbox: {sandbox_error}"
                if self.logger:
                    self.logger.log_error(error_msg)
                raise RuntimeError(f"infrastructure failure: {error_msg}")

            # 4. Open file in PowerPoint Online
            try:
                self.sandbox.open(self.edit_link)
            except Exception as open_error:
                error_msg = f"Failed to open file in sandbox: {open_error}"
                if self.logger:
                    self.logger.log_error(error_msg)
                raise RuntimeError(f"infrastructure failure: {error_msg}")

            # 5. Wait for Office Online to load
            self._wait_for_office_online_ready(max_retries=self.config.max_retries)
            time.sleep(2)  # Additional stabilization time

            # 6. Set up PowerPoint classic ribbon (if PPT file)
            if str(self.task.input_file_path).lower().endswith((".pptx", ".ppt")):
                try:
                    from ppteval.utils.powerpoint import ensure_classic_ribbon_always_show

                    print("[ScreenEnv] Setting up PowerPoint classic ribbon...")
                    if self.logger:
                        self.logger.log_info("Setting up classic ribbon")

                    ribbon_success = ensure_classic_ribbon_always_show(
                        sandbox=self.sandbox,
                        verbose=True
                    )

                    if ribbon_success:
                        print("[ScreenEnv] [ok] Classic ribbon setup successful")
                        if self.logger:
                            self.logger.log_info("Classic ribbon setup successful")
                    else:
                        print("[ScreenEnv] [warn] Classic ribbon setup had issues")
                        if self.logger:
                            self.logger.log_info("Classic ribbon setup had issues")

                except Exception as ribbon_error:
                    print(f"[ScreenEnv] [warn] Failed to set up classic ribbon: {ribbon_error}")
                    if self.logger:
                        self.logger.log_error(f"Ribbon setup error: {ribbon_error}")
                    # Continue anyway

            # 7. Take initial screenshot
            screenshot = self.sandbox.desktop_screenshot()

            if self.logger:
                self.logger.log_info("Setup complete, initial screenshot captured")

            return GUIState(screenshot=screenshot, done=False)

        except Exception as e:
            # Cleanup on error
            if self.sandbox:
                try:
                    self.sandbox.close()
                except Exception:
                    pass
                self.sandbox = None

            # Re-raise infrastructure failures as-is
            if "infrastructure failure:" in str(e):
                raise
            else:
                raise RuntimeError(f"infrastructure failure: Setup failed: {e}")

    def update(self, action: Action) -> GUIState:
        """
        Execute action and return new state.
        Executes parsed actions through the configured agent action space.
        """
        if not self.sandbox:
            raise RuntimeError("Environment not set up. Call setup() first.")

        self.current_step += 1

        # Check if terminal action
        if action.is_terminal():
            if self.logger:
                self.logger.log_info(f"Terminal action: {action.action_type}")

            # Take final screenshot
            time.sleep(self.config.step_delay)
            screenshot = self.sandbox.desktop_screenshot()

            return GUIState(screenshot=screenshot, done=True)

        # Execute action (translate to sandbox commands)
        action_result = None
        try:
            action_result = self._execute_sandbox_action(action)
        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Action execution error: {e}")
            # Don't fail the task, just log and continue

        # Wait for UI updates
        time.sleep(self.config.step_delay)

        # Capture screenshot
        screenshot = action_result if isinstance(action_result, bytes) else self.sandbox.desktop_screenshot()

        return GUIState(screenshot=screenshot, done=False)

    def _execute_sandbox_action(self, action: Action):
        """
        Translate Action to sandbox commands and execute.
        Delegates sandbox-specific behavior to the configured action space.
        """
        return self.action_space.execute(self.sandbox, action)

    def cleanup(self) -> None:
        """Close sandbox and cleanup resources."""
        if self.sandbox:
            try:
                self.sandbox.close()
            except Exception as e:
                if self.logger:
                    self.logger.log_error(f"Error closing sandbox: {e}")
            finally:
                self.sandbox = None

        if self.logger:
            self.logger.log_info("Environment cleanup complete")

    def close(self) -> None:
        """Alias for cleanup() for consistency with agent interface."""
        self.cleanup()

    def download_artifacts(self) -> dict[str, Path]:
        """
        Download final file and slide images from the live session.
        Downloads to working_dir, then copies to result_dir.
        """
        artifacts = {}

        if not self.remote_file_path:
            if self.logger:
                self.logger.log_error("No remote file path available")
            return artifacts

        try:
            # Use working_dir if set, otherwise create temp dir
            if not self.working_dir:
                import tempfile
                self.working_dir = Path(tempfile.mkdtemp(prefix=f"ppteval_{self.task.task_id}_"))

            # 1. Download modified file as a .pptx from the LIVE PowerPoint
            #    Online session (File > Save a Copy > Download a Copy). This
            #    captures the in-memory editor state, bypassing OneDrive's
            #    autosave debounce that otherwise produces a stale .pptx
            #    while the exported images already show the latest edit.
            #
            #    Mirrors the slide-images flow below: the browser writes the
            #    file inside the sandbox, then we pull it back to the host via
            #    sandbox.download_file_from_remote (the only mechanism that
            #    works uniformly across local Windows and remote WSL/Azure ML
            #    CI sandboxes — Playwright's save_as() does not cross the
            #    sandbox boundary reliably).
            if self.sandbox:
                try:
                    if self.logger:
                        self.logger.log_info(
                            "Downloading PPTX from live session (File > Save a Copy > Download a Copy)..."
                        )

                    remote_pptx = download_powerpoint_as_pptx_sync(
                        sandbox=self.sandbox,
                        download_dir=str(self.working_dir),
                        verbose=True,
                    )

                    if not remote_pptx:
                        raise RuntimeError(
                            "download_powerpoint_as_pptx_sync returned None"
                        )

                    # Mirror images path resolution: absolute path is used as-is;
                    # relative names are resolved under the sandbox desktop dir.
                    if remote_pptx.startswith("/"):
                        remote_path = remote_pptx
                    else:
                        remote_pptx_obj = Path(remote_pptx)
                        remote_path = (
                            f"/home/user/desktop/{remote_pptx_obj.parent}/{remote_pptx_obj.name}"
                        )

                    # Use legacy task_id formatting locally for compatibility.
                    upload_name = self.local_file_name or Path(self.remote_file_path).name
                    working_file = self.working_dir / upload_name

                    if self.logger:
                        self.logger.log_info(
                            f"Downloading PPTX from {remote_path} to {working_file}"
                        )

                    self.sandbox.download_file_from_remote(
                        remote_path, str(working_file)
                    )

                    if self.logger:
                        self.logger.log_info(
                            f"Downloaded live-session PPTX to working dir: {working_file}"
                        )

                    if self.result_dir:
                        import shutil
                        result_file = self.result_dir / upload_name
                        shutil.copy2(str(working_file), str(result_file))
                        artifacts["file"] = result_file
                        if self.logger:
                            self.logger.log_info(
                                f"Copied PPTX to result dir: {result_file}"
                            )
                    else:
                        artifacts["file"] = working_file

                except Exception as live_pptx_error:
                    if self.logger:
                        self.logger.log_error(
                            f"Live-session PPTX download failed, falling back to OneDrive: {live_pptx_error}"
                        )
                    # Fallback: OneDrive blob (stale-by-autosave risk known).
                    try:
                        local_file = self.onedrive_client.download_file(
                            self.remote_file_path,
                            str(self.working_dir),
                        )
                        working_file = Path(local_file)
                        if self.logger:
                            self.logger.log_info(
                                f"OneDrive fallback downloaded to working dir: {working_file}"
                            )
                        if self.result_dir:
                            import shutil
                            result_file = self.result_dir / working_file.name
                            shutil.copy2(str(working_file), str(result_file))
                            artifacts["file"] = result_file
                        else:
                            artifacts["file"] = working_file
                    except Exception as download_error:
                        if self.logger:
                            self.logger.log_error(
                                f"OneDrive fallback also failed: {download_error}"
                            )

            # Record the OneDrive remote path so result.json can trace the
            # local artifact back to the exact OneDrive blob the agent edited.
            if self.remote_file_path:
                artifacts["remote_file_path"] = self.remote_file_path

            # 2. Download slide images from the live session.
            if self.sandbox:
                try:
                    if self.logger:
                        self.logger.log_info("Downloading PowerPoint slides as images from live session...")

                    images_zip_name = download_powerpoint_as_images_sync(
                        sandbox=self.sandbox,
                        download_dir=str(self.working_dir),
                        verbose=True,
                        download_timeout=10
                    )

                    if images_zip_name:
                        # Determine remote path (download_powerpoint_as_images_sync returns the path)
                        if images_zip_name.startswith("/"):
                            remote_path = images_zip_name
                        else:
                            images_zip_name_obj = Path(images_zip_name)
                            remote_path = f"/home/user/desktop/{images_zip_name_obj.parent}/{images_zip_name_obj.name}"

                        # Download to working directory first
                        # PPTVerifier looks for Path(modified_file_path).with_suffix(".zip")
                        zip_name = Path(self.local_file_name).with_suffix(".zip").name if self.local_file_name else Path(self.remote_file_path).with_suffix(".zip").name
                        working_zip = self.working_dir / zip_name

                        if self.logger:
                            self.logger.log_info(f"Downloading PowerPoint images zip from {remote_path} to {working_zip}")

                        # Download the file from sandbox to working directory
                        try:
                            self.sandbox.download_file_from_remote(remote_path, str(working_zip))

                            if self.logger:
                                self.logger.log_info(f"Downloaded slide images to working dir: {working_zip}")

                            # Copy to result directory if set
                            if self.result_dir and "file" in artifacts:
                                import shutil
                                result_zip = artifacts["file"].with_suffix(".zip")
                                shutil.copy2(str(working_zip), str(result_zip))
                                artifacts["images_zip"] = result_zip

                                if self.logger:
                                    self.logger.log_info(f"Copied slide images to result dir: {result_zip}")
                            else:
                                artifacts["images_zip"] = working_zip
                        except Exception as download_error:
                            if self.logger:
                                self.logger.log_error(f"Failed to download PowerPoint images via sandbox: {download_error}")
                    else:
                        if self.logger:
                            self.logger.log_warning("No slide images downloaded from live session")

                except Exception as images_error:
                    if self.logger:
                        self.logger.log_error(f"Failed to download slide images from live session: {images_error}")

            # 3. Add original file path for grading
            artifacts["original_file"] = self.task.input_file_path

            return artifacts

        except Exception as e:
            if self.logger:
                self.logger.log_error(f"Error downloading artifacts: {e}")
            return artifacts
