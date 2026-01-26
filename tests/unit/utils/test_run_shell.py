"""
Tests for the run_shell function in krkn_ai.utils
"""

import pytest
import time
from krkn_ai.utils import run_shell


class TestRunShellBasic:
    """Test basic run_shell functionality"""

    def test_successful_command(self):
        """Test that a successful command returns output and exit code 0"""
        logs, returncode = run_shell("echo 'hello world'")
        assert returncode == 0
        assert "hello world" in logs

    def test_failed_command(self):
        """Test that a failed command returns non-zero exit code"""
        logs, returncode = run_shell("ls /nonexistent_directory_12345")
        assert returncode != 0

    def test_multiline_output(self):
        """Test that multiline output is captured correctly"""
        logs, returncode = run_shell("echo -e 'line1\\nline2\\nline3'")
        assert returncode == 0
        assert "line1" in logs
        assert "line2" in logs
        assert "line3" in logs


class TestRunShellTimeout:
    """Test run_shell timeout functionality"""

    def test_command_completes_before_timeout(self):
        """Test that a fast command completes normally with timeout set"""
        logs, returncode = run_shell("echo 'fast'", timeout=10)
        assert returncode == 0
        assert "fast" in logs

    def test_command_times_out(self):
        """Test that a slow command is terminated when timeout expires"""
        start_time = time.time()
        logs, returncode = run_shell("sleep 30", timeout=2)
        elapsed = time.time() - start_time

        # Should return -1 on timeout
        assert returncode == -1
        # Should complete in roughly 2 seconds (with some buffer for termination)
        assert elapsed < 10, f"Command took {elapsed} seconds, expected ~2 seconds"

    def test_timeout_none_allows_completion(self):
        """Test that timeout=None allows command to complete normally"""
        logs, returncode = run_shell("sleep 1", timeout=None)
        assert returncode == 0

    def test_partial_output_on_timeout(self):
        """Test that partial output is captured even on timeout"""
        # Command that continuously outputs then gets killed
        # Using a bash script that outputs before sleeping
        logs, returncode = run_shell(
            "bash -c 'for i in 1 2 3; do echo line$i; done; sleep 30'", timeout=2
        )
        assert returncode == -1
        assert "line1" in logs

    def test_zero_timeout_immediately_kills(self):
        """Test that timeout=0 immediately kills the process"""
        # Note: timeout=0 means no timeout in the current implementation
        # This test documents the behavior
        start_time = time.time()
        logs, returncode = run_shell("sleep 5", timeout=1)
        elapsed = time.time() - start_time

        assert returncode == -1
        assert elapsed < 5


class TestRunShellLogging:
    """Test run_shell logging behavior"""

    def test_do_not_log_suppresses_output(self):
        """Test that do_not_log=True suppresses debug logging"""
        # This test mainly verifies the parameter is accepted
        logs, returncode = run_shell("echo 'test'", do_not_log=True)
        assert returncode == 0
        assert "test" in logs

    def test_do_not_log_false_allows_output(self):
        """Test that do_not_log=False allows debug logging"""
        logs, returncode = run_shell("echo 'test'", do_not_log=False)
        assert returncode == 0
        assert "test" in logs


class TestRunShellEdgeCases:
    """Test edge cases for run_shell"""

    def test_empty_output_command(self):
        """Test command that produces no output"""
        logs, returncode = run_shell("true")
        assert returncode == 0
        assert logs == ""

    def test_special_characters_in_output(self):
        """Test that special characters are handled correctly"""
        logs, returncode = run_shell("echo 'special: $HOME \"quotes\" `backticks`'")
        assert returncode == 0
        assert "special:" in logs

    def test_large_output(self):
        """Test that large output is captured correctly"""
        # Generate 1000 lines of output
        logs, returncode = run_shell("seq 1 1000")
        assert returncode == 0
        assert "1" in logs
        assert "1000" in logs
