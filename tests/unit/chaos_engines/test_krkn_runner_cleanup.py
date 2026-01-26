"""
Unit tests for KrknRunner temporary file cleanup functionality.
"""

import os
import tempfile
from unittest.mock import patch

import pytest

from krkn_ai.chaos_engines.krkn_runner import KrknRunner
from krkn_ai.models.app import KrknRunnerType
from krkn_ai.models.config import ConfigFile, FitnessFunction
from krkn_ai.models.cluster_components import ClusterComponents


class TestKrknRunnerCleanup:
    """Test temporary file cleanup in KrknRunner."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return ConfigFile(
            kubeconfig_file_path="/tmp/test_kubeconfig",
            fitness_function=FitnessFunction(query="test_query"),
            cluster_components=ClusterComponents(),
        )

    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary output directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client")
    def test_krkn_runner_initializes_with_empty_temp_files(
        self, mock_prom, config, temp_output_dir
    ):
        """Verify that KrknRunner initializes with empty temp files list."""
        runner = KrknRunner(
            config, temp_output_dir, runner_type=KrknRunnerType.CLI_RUNNER
        )
        assert runner._temp_files == []
        assert isinstance(runner._temp_files, list)

    @patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client")
    def test_cleanup_temp_files_removes_tracked_files(
        self, mock_prom, config, temp_output_dir
    ):
        """Verify that __cleanup_temp_files removes tracked temporary files."""
        runner = KrknRunner(
            config, temp_output_dir, runner_type=KrknRunnerType.CLI_RUNNER
        )

        # Create some temporary files and track them
        temp_file1 = os.path.join(temp_output_dir, "temp1.json")
        temp_file2 = os.path.join(temp_output_dir, "temp2.json")

        with open(temp_file1, "w") as f:
            f.write("test content 1")
        with open(temp_file2, "w") as f:
            f.write("test content 2")

        # Verify files exist
        assert os.path.exists(temp_file1)
        assert os.path.exists(temp_file2)

        # Track files for cleanup
        runner._temp_files.append(temp_file1)
        runner._temp_files.append(temp_file2)

        # Call cleanup
        runner._KrknRunner__cleanup_temp_files()

        # Verify files were removed
        assert not os.path.exists(temp_file1)
        assert not os.path.exists(temp_file2)

        # Verify temp files list is cleared
        assert runner._temp_files == []

    @patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client")
    def test_cleanup_temp_files_clears_list_even_if_files_dont_exist(
        self, mock_prom, config, temp_output_dir
    ):
        """Verify cleanup clears the list even if files don't exist."""
        runner = KrknRunner(
            config, temp_output_dir, runner_type=KrknRunnerType.CLI_RUNNER
        )

        # Track non-existent files
        runner._temp_files.append("/nonexistent/file1.json")
        runner._temp_files.append("/nonexistent/file2.json")

        # Call cleanup - should not raise error
        runner._KrknRunner__cleanup_temp_files()

        # Verify temp files list is cleared
        assert runner._temp_files == []

    @patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client")
    def test_cleanup_ignores_removal_errors(self, mock_prom, config, temp_output_dir):
        """Verify cleanup continues even if file removal fails."""
        runner = KrknRunner(
            config, temp_output_dir, runner_type=KrknRunnerType.CLI_RUNNER
        )

        # Create a temp file and track it
        temp_file = os.path.join(temp_output_dir, "temp.json")
        with open(temp_file, "w") as f:
            f.write("test content")

        runner._temp_files.append(temp_file)

        # Mock os.remove to raise an exception
        with patch("os.remove", side_effect=PermissionError("Mock permission error")):
            # Should not raise error despite removal failure
            runner._KrknRunner__cleanup_temp_files()

        # Verify temp files list is cleared
        assert runner._temp_files == []
