"""
run_shell unit tests
"""

import pytest

from krkn_ai.models.custom_errors import ShellCommandTimeoutError
from krkn_ai.utils import run_shell


class TestRunShell:
    """Test run_shell timeout behavior"""

    def test_timeout_raises_shell_command_timeout_error(self):
        with pytest.raises(ShellCommandTimeoutError):
            run_shell("sleep 1", timeout=0.05)

    def test_run_shell_timeout_no_fd_leak(self):
        import os
        import sys
        import gc

        fd_dir = "/dev/fd" if sys.platform == "darwin" else "/proc/self/fd"
        if not os.path.exists(fd_dir):
            pytest.skip("System does not support FD list directory check")

        # Clear garbage collection first to start clean
        gc.collect()
        initial_fds = len(os.listdir(fd_dir))

        exceptions = []
        for _ in range(5):
            try:
                run_shell("sleep 1", timeout=0.05)
            except ShellCommandTimeoutError as e:
                exceptions.append(e)

        # Assert that the active FD count did not grow significantly.
        # We allow a small tolerance (+1) to avoid flakiness from unrelated FDs,
        # but a real leak would easily fail this test as it would leak 5+ FDs.
        final_fds = len(os.listdir(fd_dir))
        assert final_fds <= initial_fds + 1, (
            f"FD leak detected: {initial_fds} -> {final_fds}"
        )

        exceptions.clear()
