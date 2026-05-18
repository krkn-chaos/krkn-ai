"""
CLI command tests
"""

import os
import tempfile
from unittest.mock import Mock, patch
from click.testing import CliRunner
from pydantic import ValidationError

from krkn_ai.cli.cmd import main
from krkn_ai.models.custom_errors import FitnessFunctionCalculationError
from krkn_ai.models.app import KrknRunnerType
from krkn_ai.models.config import ConfigFile


class TestRunCommand:
    """Test core behavior of run command"""

    def test_run_with_valid_config_succeeds(self, minimal_config, temp_output_dir):
        """Test command succeeds when using valid config file"""
        runner = CliRunner()

        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml

            config_dict = {
                "kubeconfig_file_path": minimal_config.kubeconfig_file_path,
                "generations": minimal_config.generations,
                "population_size": minimal_config.population_size,
                "fitness_function": {
                    "query": minimal_config.fitness_function.query,
                    "type": minimal_config.fitness_function.type.value,
                },
                "scenario": {"pod_scenarios": {"enable": True}},
            }
            yaml.dump(config_dict, f)
            config_path = f.name

        try:
            with patch("krkn_ai.cli.cmd.read_config_from_file") as mock_read:
                with patch("krkn_ai.cli.cmd.GeneticAlgorithm") as mock_ga_class:
                    mock_read.return_value = minimal_config
                    mock_ga = Mock()
                    mock_ga_class.return_value = mock_ga

                    override_kubeconfig = "/override/kubeconfig"
                    result = runner.invoke(
                        main,
                        [
                            "run",
                            "--config",
                            config_path,
                            "--output",
                            temp_output_dir,
                            "--kubeconfig",
                            override_kubeconfig,
                        ],
                    )

                    assert result.exit_code == 0
                    # Verify kubeconfig override was passed to read_config_from_file
                    mock_read.assert_called_once_with(
                        config_path, (), override_kubeconfig
                    )
                    mock_ga.simulate.assert_called_once()
                    mock_ga.save.assert_called_once()
        finally:
            os.unlink(config_path)

    def test_run_fails_when_config_missing_or_invalid(self, temp_output_dir):
        """Test command fails when config file is missing or invalid"""
        runner = CliRunner()

        with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            # Test empty config file path
            result = runner.invoke(
                main, ["run", "--config", "", "--output", temp_output_dir]
            )
            assert result.exit_code == 1
            mock_logger.error.assert_called_once()
            assert "Config file invalid" in str(mock_logger.error.call_args)

            # Test non-existent config file
            mock_logger.reset_mock()
            result = runner.invoke(
                main,
                [
                    "run",
                    "--config",
                    "/nonexistent/file.yaml",
                    "--output",
                    temp_output_dir,
                ],
            )
            assert result.exit_code == 1
            mock_logger.error.assert_called_once()
            assert "Config file not found" in str(mock_logger.error.call_args)

    def test_run_handles_config_parsing_errors(self, temp_output_dir):
        """Test config file parsing error handling"""
        runner = CliRunner()

        # Create temporary config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content: [")
            config_path = f.name

        try:
            with patch("krkn_ai.cli.cmd.read_config_from_file") as mock_read:
                with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
                    mock_logger = Mock()
                    mock_get_logger.return_value = mock_logger

                    # Test KeyError
                    mock_read.side_effect = KeyError("missing_key")
                    result = runner.invoke(
                        main,
                        ["run", "--config", config_path, "--output", temp_output_dir],
                    )
                    assert result.exit_code == 1
                    mock_logger.error.assert_called_once()
                    assert "missing key" in str(mock_logger.error.call_args).lower()

                    mock_logger.reset_mock()
                    try:
                        ConfigFile()  # This will raise ValidationError
                    except ValidationError as e:
                        validation_error = e
                        mock_read.side_effect = validation_error
                    result = runner.invoke(
                        main,
                        ["run", "--config", config_path, "--output", temp_output_dir],
                    )
                    assert result.exit_code == 1
                    mock_logger.error.assert_called_once()
                    assert "Unable to parse config file" in str(
                        mock_logger.error.call_args
                    )
        finally:
            os.unlink(config_path)

    def test_run_converts_runner_type(self, minimal_config, temp_output_dir):
        """Test runner_type string to enum conversion"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml

            config_dict = {
                "kubeconfig_file_path": minimal_config.kubeconfig_file_path,
                "generations": minimal_config.generations,
                "population_size": minimal_config.population_size,
                "fitness_function": {
                    "query": minimal_config.fitness_function.query,
                    "type": minimal_config.fitness_function.type.value,
                },
                "scenario": {"pod_scenarios": {"enable": True}},
            }
            yaml.dump(config_dict, f)
            config_path = f.name

        try:
            with patch("krkn_ai.cli.cmd.read_config_from_file") as mock_read:
                with patch("krkn_ai.cli.cmd.GeneticAlgorithm") as mock_ga_class:
                    mock_read.return_value = minimal_config
                    mock_ga = Mock()
                    mock_ga_class.return_value = mock_ga

                    # Test runner_type conversion (krknctl -> CLI_RUNNER)
                    result = runner.invoke(
                        main,
                        [
                            "run",
                            "--config",
                            config_path,
                            "--output",
                            temp_output_dir,
                            "--runner-type",
                            "krknctl",
                        ],
                    )
                    assert result.exit_code == 0
                    call_args = mock_ga_class.call_args
                    assert call_args[1]["runner_type"] == KrknRunnerType.CLI_RUNNER
        finally:
            os.unlink(config_path)

    def test_run_handles_genetic_algorithm_errors(
        self, minimal_config, temp_output_dir
    ):
        """Test genetic algorithm error handling"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml

            config_dict = {
                "kubeconfig_file_path": minimal_config.kubeconfig_file_path,
                "generations": minimal_config.generations,
                "population_size": minimal_config.population_size,
                "fitness_function": {
                    "query": minimal_config.fitness_function.query,
                    "type": minimal_config.fitness_function.type.value,
                },
                "scenario": {"pod_scenarios": {"enable": True}},
            }
            yaml.dump(config_dict, f)
            config_path = f.name

        try:
            with patch("krkn_ai.cli.cmd.read_config_from_file") as mock_read:
                with patch("krkn_ai.cli.cmd.GeneticAlgorithm") as mock_ga_class:
                    with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
                        mock_read.return_value = minimal_config
                        mock_ga = Mock()
                        mock_ga_class.return_value = mock_ga
                        mock_logger = Mock()
                        mock_get_logger.return_value = mock_logger

                        # Test FitnessFunctionCalculationError handling
                        mock_ga.simulate.side_effect = FitnessFunctionCalculationError(
                            "Calculation failed"
                        )
                        result = runner.invoke(
                            main,
                            [
                                "run",
                                "--config",
                                config_path,
                                "--output",
                                temp_output_dir,
                            ],
                        )
                        assert result.exit_code == 1
                        mock_logger.error.assert_called_once()
                        assert "Unable to calculate fitness function score" in str(
                            mock_logger.error.call_args
                        )
        finally:
            os.unlink(config_path)


class TestDiscoverCommand:
    """Test core behavior of discover command"""

    def test_discover_with_valid_kubeconfig_succeeds(
        self, mock_cluster_components, temp_output_dir
    ):
        """Test command succeeds when using valid kubeconfig"""
        runner = CliRunner()

        # Create temporary kubeconfig file
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("apiVersion: v1\nkind: Config")
            kubeconfig_path = f.name

        try:
            with patch("krkn_ai.cli.cmd.ClusterManager") as mock_cluster_manager_class:
                with patch("krkn_ai.cli.cmd.create_krkn_ai_template") as mock_template:
                    mock_manager = Mock()
                    mock_manager.discover_components.return_value = (
                        mock_cluster_components
                    )
                    mock_cluster_manager_class.return_value = mock_manager
                    mock_template.return_value = "generated_template_content"

                    output_file = os.path.join(temp_output_dir, "output.yaml")
                    result = runner.invoke(
                        main,
                        [
                            "discover",
                            "--kubeconfig",
                            kubeconfig_path,
                            "--output",
                            output_file,
                        ],
                    )

                    assert result.exit_code == 0
                    mock_cluster_manager_class.assert_called_once_with(kubeconfig_path)
                    mock_manager.discover_components.assert_called_once()
                    mock_template.assert_called_once()
                    assert os.path.exists(output_file)
                    with open(output_file, "r") as f:
                        assert f.read() == "generated_template_content"
        finally:
            os.unlink(kubeconfig_path)

    def test_discover_fails_when_kubeconfig_missing(self, temp_output_dir):
        """Test command fails when kubeconfig is missing"""
        runner = CliRunner()

        # Test empty kubeconfig path
        with patch.dict(os.environ, {}, clear=True):
            with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
                mock_logger = Mock()
                mock_get_logger.return_value = mock_logger

                result = runner.invoke(
                    main,
                    [
                        "discover",
                        "--kubeconfig",
                        "",
                        "--output",
                        os.path.join(temp_output_dir, "output.yaml"),
                    ],
                )
                assert result.exit_code == 1
                mock_logger.error.assert_called_once()
                assert "Kubeconfig file not found" in str(mock_logger.error.call_args)
