"""
run_shell unit tests
"""

import pytest
import sys

from krkn_ai.models.custom_errors import ShellCommandTimeoutError
from krkn_ai.utils import run_shell


class TestRunShell:
    """Test run_shell timeout behavior"""

    def test_timeout_raises_shell_command_timeout_error(self):
        # Use sys.executable to run a portable Python sleep so the test
        # works on Windows and Unix (avoids relying on external 'sleep').
        # Quote the executable path so backslashes are preserved on Windows.
        exe = sys.executable
        cmd = f'"{exe}" -c "import time; time.sleep(10)"'
        with pytest.raises(ShellCommandTimeoutError):
            run_shell(cmd, timeout=5)
