"""
run_shell unit tests
"""

import os
import signal
import shlex
import sys
import threading
import time
import pytest
from unittest.mock import patch

import krkn_ai.utils as utils_module
from krkn_ai.models.custom_errors import ShellCommandTimeoutError
from krkn_ai.utils import run_shell


class TestRunShell:
    """Test run_shell timeout behavior"""

    def test_timeout_raises_shell_command_timeout_error(self):
        with pytest.raises(ShellCommandTimeoutError):
            run_shell("sleep 10", timeout=5)

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

    def test_cancel_event_terminates_and_reaps_process_group(self, tmp_path):
        pid_file = tmp_path / "child.pid"
        script = (
            "import signal, subprocess, sys; "
            "signal.signal(signal.SIGTERM, lambda *_: None); "
            "child = subprocess.Popen(['sleep', '30']); "
            "open(sys.argv[1], 'w').write(str(child.pid)); "
            "print('started', flush=True); "
            "child.wait()"
        )
        command = (
            f"{shlex.quote(sys.executable)} -c {shlex.quote(script)} "
            f"{shlex.quote(str(pid_file))}"
        )
        cancellation_event = threading.Event()
        result = []
        worker = threading.Thread(
            target=lambda: result.append(
                run_shell(command, cancellation_event=cancellation_event)
            )
        )

        worker.start()
        try:
            deadline = time.monotonic() + 5
            child_pid = None
            while time.monotonic() < deadline:
                if pid_file.exists() and (content := pid_file.read_text()):
                    child_pid = int(content)
                    break
                time.sleep(0.01)
            assert child_pid is not None

            cancellation_event.set()
            worker.join(timeout=3)
            assert not worker.is_alive()
            assert result[0][1] == 0
            assert "started\n" in result[0][0]
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            cancellation_event.set()
            worker.join(timeout=8)

    def test_cancellation_kills_a_process_ignoring_term(self, tmp_path, monkeypatch):
        ready = tmp_path / "ready"
        script = (
            "import signal, sys, time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "open(sys.argv[1], 'w').write('ready'); "
            "time.sleep(30)"
        )
        command = shlex.join([sys.executable, "-c", script, str(ready)])
        cancellation_event = threading.Event()
        result = []
        terminate = utils_module._terminate_process_group
        monkeypatch.setattr(
            utils_module,
            "_terminate_process_group",
            lambda process: terminate(process, grace_period=0.1),
        )
        worker = threading.Thread(
            target=lambda: result.append(
                run_shell(command, cancellation_event=cancellation_event)
            )
        )
        worker.start()
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists()
            cancellation_event.set()
            worker.join(timeout=3)
            assert not worker.is_alive()
            assert result[0][1] == -signal.SIGKILL
        finally:
            cancellation_event.set()
            worker.join(timeout=8)

    def test_pre_cancelled_event_does_not_launch_process(self):
        cancellation_event = threading.Event()
        cancellation_event.set()

        with patch("krkn_ai.utils.subprocess.Popen") as mock_popen:
            logs, returncode = run_shell(
                "sleep 10", cancellation_event=cancellation_event
            )

        mock_popen.assert_not_called()
        assert logs == ""
        assert returncode == -15
