"""
CLI command tests
"""

import os
import tempfile
from unittest.mock import Mock, patch

import pytest
import yaml
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
                "generations": minimal_config.genetic.generations,
                "population_size": minimal_config.genetic.population_size,
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

    def test_run_uses_default_output_when_flag_is_omitted(self, minimal_config):
        """Test command uses default output directory when --output is omitted"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            import yaml

            config_dict = {
                "kubeconfig_file_path": minimal_config.kubeconfig_file_path,
                "generations": minimal_config.genetic.generations,
                "population_size": minimal_config.genetic.population_size,
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

                    with runner.isolated_filesystem():
                        result = runner.invoke(
                            main,
                            [
                                "run",
                                "--config",
                                config_path,
                            ],
                        )

                    assert result.exit_code == 0, result.exception
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
                "generations": minimal_config.genetic.generations,
                "population_size": minimal_config.genetic.population_size,
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
                "generations": minimal_config.genetic.generations,
                "population_size": minimal_config.genetic.population_size,
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
                with patch("krkn_ai.cli.cmd.save_discovery") as mock_save:
                    mock_manager = Mock()
                    mock_manager.discover_components.return_value = (
                        mock_cluster_components
                    )
                    mock_cluster_manager_class.return_value = mock_manager

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
                    mock_save.assert_called_once()
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

    def test_discover_defaults_to_skip_strategy(
        self, mock_cluster_components, temp_output_dir
    ):
        """Without the flag, discover passes the skip strategy through."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("apiVersion: v1\nkind: Config")
            kubeconfig_path = f.name

        try:
            with patch("krkn_ai.cli.cmd.ClusterManager") as mock_manager_class:
                with patch("krkn_ai.cli.cmd.save_discovery") as mock_save:
                    mock_manager_class.return_value.discover_components.return_value = (
                        mock_cluster_components
                    )
                    output_file = os.path.join(temp_output_dir, "output.yaml")
                    result = runner.invoke(
                        main,
                        ["discover", "-k", kubeconfig_path, "-o", output_file],
                    )

                    assert result.exit_code == 0
                    mock_save.assert_called_once()
                    output_arg, strategy_arg = mock_save.call_args.args[:2]
                    assert output_arg == output_file
                    assert strategy_arg == "skip"
        finally:
            os.unlink(kubeconfig_path)

    def test_discover_verify_chosen_strategy(
        self, mock_cluster_components, temp_output_dir
    ):
        """Verify the chosen --save-strategy is used."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("apiVersion: v1\nkind: Config")
            kubeconfig_path = f.name

        try:
            with patch("krkn_ai.cli.cmd.ClusterManager") as mock_manager_class:
                with patch("krkn_ai.cli.cmd.save_discovery") as mock_save:
                    mock_manager_class.return_value.discover_components.return_value = (
                        mock_cluster_components
                    )
                    output_file = os.path.join(temp_output_dir, "output.yaml")
                    result = runner.invoke(
                        main,
                        [
                            "discover",
                            "-k",
                            kubeconfig_path,
                            "-o",
                            output_file,
                            "--save-strategy",
                            "merge",
                        ],
                    )

                    assert result.exit_code == 0
                    assert mock_save.call_args.args[1] == "merge"
        finally:
            os.unlink(kubeconfig_path)

    @pytest.mark.parametrize(
        "strategy, file_exists, expect_recommend_calls",
        [
            ("skip", False, 1),  # new file
            ("skip", True, 0),  # existing
            ("overwrite", False, 1),  # no file
            ("overwrite", True, 1),  # always writes fresh
            ("merge", False, 1),  # nothing to merge
            ("merge", True, 0),  # merge preserves existing
        ],
    )
    def test_discover_recommends_only_on_fresh_write(
        self,
        strategy,
        file_exists,
        expect_recommend_calls,
        mock_cluster_components,
        temp_output_dir,
    ):
        """recommend runs only when discover writes a fresh config."""
        runner = CliRunner()
        output_file = os.path.join(temp_output_dir, "output.yaml")
        if file_exists:
            with open(output_file, "w") as f:
                f.write("existing: true\n")

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("apiVersion: v1\nkind: Config")
            kubeconfig_path = f.name

        try:
            with (
                patch("krkn_ai.cli.cmd.ClusterManager") as mock_manager_class,
                patch("krkn_ai.cli.cmd.save_discovery"),
                patch(
                    "krkn_ai.cli.cmd.ScenarioFactory.recommend_enabled_scenarios",
                    return_value={"pod_scenarios": True, "pvc_scenarios": False},
                ) as mock_rec,
            ):
                mock_manager_class.return_value.discover_components.return_value = (
                    mock_cluster_components
                )
                result = runner.invoke(
                    main,
                    [
                        "discover",
                        "-k",
                        kubeconfig_path,
                        "-o",
                        output_file,
                        "--save-strategy",
                        strategy,
                    ],
                )
                assert result.exit_code == 0
                assert mock_rec.call_count == expect_recommend_calls
        finally:
            os.unlink(kubeconfig_path)

    def test_discover_writes_recommended_scenarios_to_file(
        self, mock_cluster_components, temp_output_dir
    ):
        """Fresh discover writes the recommended scenarios to the output file."""
        runner = CliRunner()
        output_file = os.path.join(temp_output_dir, "output.yaml")

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("apiVersion: v1\nkind: Config")
            kubeconfig_path = f.name

        try:
            with (
                patch("krkn_ai.cli.cmd.ClusterManager") as mock_manager_class,
                patch(
                    "krkn_ai.cli.cmd.ScenarioFactory.recommend_enabled_scenarios",
                    return_value={
                        "pvc_scenarios": True,
                        "pod_scenarios": False,
                    },
                ),
            ):
                manager = mock_manager_class.return_value
                manager.discover_components.return_value = mock_cluster_components
                manager.recommend_health_checks.return_value = []
                result = runner.invoke(
                    main, ["discover", "-k", kubeconfig_path, "-o", output_file]
                )

                assert result.exit_code == 0
                data = yaml.safe_load(open(output_file))
                # recommended scenario enabled; an unrecommended one stays off
                assert data["scenario"]["pvc-scenarios"]["enable"] is True
                assert data["scenario"]["pod-scenarios"]["enable"] is False
        finally:
            os.unlink(kubeconfig_path)

    @pytest.mark.parametrize(
        "strategy, file_exists, expect_recommend_calls",
        [
            ("skip", False, 1),
            ("skip", True, 0),
            ("overwrite", False, 1),
            ("overwrite", True, 1),
            ("merge", False, 1),
            ("merge", True, 0),
        ],
    )
    def test_discover_recommends_health_checks_only_on_fresh_write(
        self,
        strategy,
        file_exists,
        expect_recommend_calls,
        mock_cluster_components,
        temp_output_dir,
    ):
        """Health-check recommendation runs only on a fresh write, like scenarios."""
        runner = CliRunner()
        output_file = os.path.join(temp_output_dir, "output.yaml")
        if file_exists:
            with open(output_file, "w") as f:
                f.write("existing: true\n")

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("apiVersion: v1\nkind: Config")
            kubeconfig_path = f.name

        try:
            with (
                patch("krkn_ai.cli.cmd.ClusterManager") as mock_manager_class,
                patch("krkn_ai.cli.cmd.save_discovery"),
                patch(
                    "krkn_ai.cli.cmd.ScenarioFactory.recommend_enabled_scenarios",
                    return_value={},
                ),
            ):
                manager = mock_manager_class.return_value
                manager.discover_components.return_value = mock_cluster_components
                manager.recommend_health_checks.return_value = []
                result = runner.invoke(
                    main,
                    [
                        "discover",
                        "-k",
                        kubeconfig_path,
                        "-o",
                        output_file,
                        "--save-strategy",
                        strategy,
                    ],
                )
                assert result.exit_code == 0
                assert (
                    manager.recommend_health_checks.call_count == expect_recommend_calls
                )
        finally:
            os.unlink(kubeconfig_path)

    def test_discover_writes_recommended_health_checks_to_file(
        self, mock_cluster_components, temp_output_dir
    ):
        """Fresh discover writes the recommended health checks to the output file."""
        runner = CliRunner()
        output_file = os.path.join(temp_output_dir, "output.yaml")
        apps = [
            {
                "name": "cart",
                "url": "http://1.2.3.4:80/health",
                "probe": True,
                "active": True,
            }
        ]

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("apiVersion: v1\nkind: Config")
            kubeconfig_path = f.name

        try:
            with (
                patch("krkn_ai.cli.cmd.ClusterManager") as mock_manager_class,
                patch(
                    "krkn_ai.cli.cmd.ScenarioFactory.recommend_enabled_scenarios",
                    return_value={},
                ),
            ):
                manager = mock_manager_class.return_value
                manager.discover_components.return_value = mock_cluster_components
                manager.recommend_health_checks.return_value = apps
                result = runner.invoke(
                    main, ["discover", "-k", kubeconfig_path, "-o", output_file]
                )

                assert result.exit_code == 0
                data = yaml.safe_load(open(output_file))
                assert data["health_checks"]["applications"] == [
                    {"name": "cart", "url": "http://1.2.3.4:80/health"}
                ]
        finally:
            os.unlink(kubeconfig_path)

    def test_discover_rejects_invalid_strategy(self):
        """An unknown --save-strategy value is rejected by click."""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("apiVersion: v1\nkind: Config")
            kubeconfig_path = f.name

        try:
            result = runner.invoke(
                main,
                ["discover", "-k", kubeconfig_path, "--save-strategy", "bogus"],
            )
            assert result.exit_code != 0
        finally:
            os.unlink(kubeconfig_path)
