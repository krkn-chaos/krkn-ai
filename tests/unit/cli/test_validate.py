"""
CLI validate command tests
"""

import os
import tempfile
from unittest.mock import Mock, patch

import yaml
from click.testing import CliRunner
from pydantic import ValidationError

from krkn_ai.cli.cmd import main


class TestValidateCommand:
    """Tests for the validate subcommand (offline config validation)."""

    def _write_config(self, content: dict) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(content, f)
            return f.name

    def test_validate_valid_config_succeeds(self, minimal_config):
        """A well-formed config passes offline validation."""
        runner = CliRunner()
        config_path = self._write_config(
            {
                "kubeconfig_file_path": minimal_config.kubeconfig_file_path,
                "generations": minimal_config.genetic.generations,
                "population_size": minimal_config.genetic.population_size,
                "fitness_function": {
                    "query": minimal_config.fitness_function.query,
                    "type": minimal_config.fitness_function.type.value,
                },
                "scenario": {"pod_scenarios": {"enable": True}},
            }
        )
        try:
            with patch("krkn_ai.cli.cmd.read_config_from_file") as mock_read:
                mock_read.return_value = minimal_config
                result = runner.invoke(main, ["validate", "-c", config_path])
                assert result.exit_code == 0
                assert "Config is valid" in result.output
                mock_read.assert_called_once()
        finally:
            os.unlink(config_path)

    def test_validate_missing_config_file_fails(self):
        """Missing config path exits non-zero."""
        runner = CliRunner()
        result = runner.invoke(main, ["validate", "-c", "/nonexistent/krkn-ai.yaml"])
        assert result.exit_code != 0

    def test_validate_invalid_config_fails(self):
        """Schema/validation errors exit non-zero with a clear message."""
        runner = CliRunner()
        config_path = self._write_config(
            {
                # Invalid: population_size must be >= 2 and rates in [0,1]
                "population_size": 1,
                "fitness_function": {"query": "up", "type": "point"},
                "scenario": {"pod_scenarios": {"enable": True}},
            }
        )
        try:
            with patch("krkn_ai.cli.cmd.read_config_from_file") as mock_read:
                mock_read.side_effect = ValidationError.from_exception_data(
                    "ConfigFile",
                    [
                        {
                            "type": "greater_than_equal",
                            "loc": ("genetic", "population_size"),
                            "msg": "Input should be greater than or equal to 2",
                            "input": 1,
                            "ctx": {"ge": 2},
                        }
                    ],
                )
                result = runner.invoke(main, ["validate", "-c", config_path])
                assert result.exit_code != 0
        finally:
            os.unlink(config_path)

    def test_validate_with_param_override(self, minimal_config):
        """-p overrides are forwarded to read_config_from_file."""
        runner = CliRunner()
        config_path = self._write_config(
            {
                "kubeconfig_file_path": minimal_config.kubeconfig_file_path,
                "fitness_function": {
                    "query": minimal_config.fitness_function.query,
                    "type": minimal_config.fitness_function.type.value,
                },
                "scenario": {"pod_scenarios": {"enable": True}},
            }
        )
        try:
            with patch("krkn_ai.cli.cmd.read_config_from_file") as mock_read:
                mock_read.return_value = minimal_config
                result = runner.invoke(
                    main,
                    ["validate", "-c", config_path, "-p", "HOST=http://localhost"],
                )
                assert result.exit_code == 0
                mock_read.assert_called_once_with(
                    config_path, ("HOST=http://localhost",), None
                )
        finally:
            os.unlink(config_path)

    def test_validate_check_connectivity_success(self, minimal_config):
        """--check-connectivity succeeds when cluster and Prometheus are reachable."""
        runner = CliRunner()
        config_path = self._write_config(
            {
                "kubeconfig_file_path": "/tmp/test-kubeconfig",
                "fitness_function": {
                    "query": minimal_config.fitness_function.query,
                    "type": minimal_config.fitness_function.type.value,
                },
                "scenario": {"pod_scenarios": {"enable": True}},
            }
        )
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("apiVersion: v1\nkind: Config")
            kube_path = f.name
        try:
            with (
                patch("krkn_ai.cli.cmd.read_config_from_file") as mock_read,
                patch("krkn_ai.cli.cmd.ClusterManager") as mock_cm_class,
                patch("krkn_ai.cli.cmd.create_prometheus_client") as mock_prom,
            ):
                mock_read.return_value = minimal_config
                mock_cm = mock_cm_class.return_value
                mock_cm.core_api.list_namespace.return_value = Mock()
                mock_prom.return_value = Mock()

                result = runner.invoke(
                    main,
                    [
                        "validate",
                        "-c",
                        config_path,
                        "-k",
                        kube_path,
                        "--check-connectivity",
                    ],
                )
                assert result.exit_code == 0
                assert "Config is valid" in result.output
                mock_cm.core_api.list_namespace.assert_called_once_with(limit=1)
                mock_prom.assert_called_once()
        finally:
            os.unlink(config_path)
            os.unlink(kube_path)

    def test_validate_check_connectivity_prometheus_failure(self, minimal_config):
        """Prometheus failure during connectivity check exits non-zero."""
        runner = CliRunner()
        config_path = self._write_config(
            {
                "kubeconfig_file_path": "/tmp/test-kubeconfig",
                "fitness_function": {
                    "query": minimal_config.fitness_function.query,
                    "type": minimal_config.fitness_function.type.value,
                },
                "scenario": {"pod_scenarios": {"enable": True}},
            }
        )
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("apiVersion: v1\nkind: Config")
            kube_path = f.name
        try:
            from krkn_ai.models.custom_errors import PrometheusConnectionError

            with (
                patch("krkn_ai.cli.cmd.read_config_from_file") as mock_read,
                patch("krkn_ai.cli.cmd.ClusterManager") as mock_cm_class,
                patch("krkn_ai.cli.cmd.create_prometheus_client") as mock_prom,
            ):
                mock_read.return_value = minimal_config
                mock_cm = mock_cm_class.return_value
                mock_cm.core_api.list_namespace.return_value = Mock()
                mock_prom.side_effect = PrometheusConnectionError("no prom")

                result = runner.invoke(
                    main,
                    [
                        "validate",
                        "-c",
                        config_path,
                        "-k",
                        kube_path,
                        "--check-connectivity",
                    ],
                )
                assert result.exit_code != 0
        finally:
            os.unlink(config_path)
            os.unlink(kube_path)
