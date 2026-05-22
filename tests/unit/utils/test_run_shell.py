"""
run_shell unit tests
"""

import pytest

from krkn_ai.models.custom_errors import ShellCommandTimeoutError
from krkn_ai.utils import run_shell


class TestRunShell:
    """Test run_shell timeout behavior"""

    def test_timeout_raises_shell_command_timeout_error(self):
        import sys
        exec_path = sys.executable.replace("\\", "/")
        cmd = f'"{exec_path}" -c "import time; time.sleep(10)"'
        with pytest.raises(ShellCommandTimeoutError):
            run_shell(cmd, timeout=5)
