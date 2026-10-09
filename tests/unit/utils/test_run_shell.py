"""
run_shell unit tests
"""

import subprocess

import pytest
from unittest.mock import patch

from krkn_ai.models.custom_errors import ShellCommandTimeoutError
from krkn_ai.utils import run_shell


class TestRunShell:
    """Test run_shell timeout behavior"""

    def test_timeout_raises_shell_command_timeout_error(self):
        with pytest.raises(ShellCommandTimeoutError):
            run_shell("sleep 10", timeout=5)

    def test_timeout_closes_stdout_pipe(self):
        """The child's stdout must be closed on the timeout path too (#328)"""
        spawned = []
        real_popen = subprocess.Popen

        def tracking_popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            spawned.append(process)
            return process

        with patch("krkn_ai.utils.subprocess.Popen", side_effect=tracking_popen):
            with pytest.raises(ShellCommandTimeoutError):
                run_shell("sleep 10", timeout=1)

        assert len(spawned) == 1
        assert spawned[0].stdout.closed
        assert spawned[0].returncode is not None

    def test_success_closes_stdout_pipe(self):
        spawned = []
        real_popen = subprocess.Popen

        def tracking_popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            spawned.append(process)
            return process

        with patch("krkn_ai.utils.subprocess.Popen", side_effect=tracking_popen):
            logs, returncode = run_shell("echo hello")

        assert returncode == 0
        assert logs.strip() == "hello"
        assert spawned[0].stdout.closed

    @patch("krkn_ai.utils.shutil.which")
    def test_command_not_found_returns_empty_string_and_127(self, mock_which):
        """Test that run_shell returns 127 when command is not in PATH"""
        mock_which.return_value = None
        logs, returncode = run_shell("krknctl --version")
        assert returncode == 127
        assert logs == ""

    @patch("krkn_ai.utils.subprocess.Popen")
    @patch("krkn_ai.utils.shutil.which", return_value="/usr/bin/podman")
    def test_permission_error_returns_empty_string_and_127(
        self, mock_which, mock_popen
    ):
        """Test that run_shell catches OSError (like PermissionError during Popen) and returns empty string and 127"""
        mock_popen.side_effect = PermissionError("Mocked permission error")
        logs, returncode = run_shell("podman --version")
        assert returncode == 127
        assert logs == ""
