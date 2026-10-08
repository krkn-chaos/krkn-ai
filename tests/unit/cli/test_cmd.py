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
from krkn_ai.models.custom_errors import (
    FitnessFunctionCalculationError,
    PrometheusConnectionError,
)
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

    def test_run_uses_supplied_run_uuid_for_engine_and_output(
        self, minimal_config, temp_output_dir
    ):
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            config_path = f.name
            f.write("algorithm: genetic\n")

        supplied_uuid = "12345678-1234-5678-1234-567812345678"
        try:
            with patch(
                "krkn_ai.cli.cmd.read_config_from_file", return_value=minimal_config
            ):
                with patch("krkn_ai.cli.cmd.GeneticAlgorithm") as mock_ga_class:
                    mock_ga = Mock()
                    mock_ga_class.return_value = mock_ga
                    result = runner.invoke(
                        main,
                        [
                            "run",
                            "--config",
                            config_path,
                            "--output",
                            temp_output_dir,
                            "--run-uuid",
                            supplied_uuid,
                        ],
                    )

                    assert result.exit_code == 0, result.exception
                    assert mock_ga_class.call_args.kwargs["run_uuid"] == supplied_uuid
                    assert mock_ga_class.call_args.kwargs["output_dir"] == os.path.join(
                        temp_output_dir, supplied_uuid
                    )
        finally:
            os.unlink(config_path)

    def test_run_generates_uuid_when_run_uuid_is_omitted(
        self, minimal_config, temp_output_dir
    ):
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            config_path = f.name
            f.write("algorithm: genetic\n")

        generated_uuid = "87654321-4321-8765-4321-876543218765"
        try:
            with patch(
                "krkn_ai.cli.cmd.read_config_from_file", return_value=minimal_config
            ):
                with patch("krkn_ai.cli.cmd.uuid.uuid4", return_value=generated_uuid):
                    with patch("krkn_ai.cli.cmd.GeneticAlgorithm") as mock_ga_class:
                        mock_ga = Mock()
                        mock_ga_class.return_value = mock_ga
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

                        assert result.exit_code == 0, result.exception
                        assert (
                            mock_ga_class.call_args.kwargs["run_uuid"] == generated_uuid
                        )
                        assert mock_ga_class.call_args.kwargs[
                            "output_dir"
                        ] == os.path.join(temp_output_dir, generated_uuid)
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

    def test_discover_recommends_fitness_queries_when_merging(
        self, mock_cluster_components, temp_output_dir
    ):
        runner = CliRunner()
        output_file = os.path.join(temp_output_dir, "output.yaml")
        with open(output_file, "w") as output:
            output.write("existing: true\n")
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as kubeconfig:
            kubeconfig.write("apiVersion: v1\nkind: Config")
            kubeconfig_path = kubeconfig.name

        try:
            with (
                patch("krkn_ai.cli.cmd.ClusterManager") as mock_manager_class,
                patch("krkn_ai.cli.cmd.save_discovery") as save_discovery,
                patch("krkn_ai.cli.cmd.create_prometheus_client"),
                patch(
                    "krkn_ai.cli.cmd.recommend_fitness_queries",
                    return_value=[
                        {
                            "query": "up",
                            "type": "point",
                            "weight": 1,
                            "enabled": True,
                        }
                    ],
                ) as recommend_fitness,
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
                        "merge",
                    ],
                )

            assert result.exit_code == 0
            recommend_fitness.assert_called_once()
            assert save_discovery.call_args.kwargs["fitness_queries"] == [
                {"query": "up", "type": "point", "weight": 1, "enabled": True}
            ]
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


class TestValidateCommand:
    """Test behavior of the validate command"""

    def _write_config(self, tmp_path, config_dict=None, text=None):
        config_path = tmp_path / "krkn-ai.yaml"
        if text is not None:
            config_path.write_text(text)
        else:
            config_path.write_text(yaml.safe_dump(config_dict))
        return str(config_path)

    def _valid_config_dict(self):
        return {
            "kubeconfig_file_path": "/tmp/kubeconfig",
            "fitness_function": {"query": "up"},
            "cluster_components": {"namespaces": [], "nodes": []},
            "scenario": {"pod_scenarios": {"enable": True}},
            "health_checks": {
                "applications": [{"name": "api", "url": "http://$HOST/health"}]
            },
        }

    def test_valid_config_succeeds_offline(self, tmp_path):
        """A valid config passes without contacting the cluster or Prometheus"""
        runner = CliRunner()
        config_path = self._write_config(tmp_path, self._valid_config_dict())

        with (
            patch("krkn_ai.cli.cmd.ClusterManager") as mock_cm,
            patch("krkn_ai.cli.cmd.create_prometheus_client") as mock_prom,
        ):
            result = runner.invoke(main, ["validate", "-c", config_path])

            assert result.exit_code == 0, result.output
            mock_cm.assert_not_called()
            mock_prom.assert_not_called()

    def test_valid_config_logs_enabled_scenarios(self, tmp_path):
        """Enabled scenarios are reported so users can confirm their config"""
        runner = CliRunner()
        config = self._valid_config_dict()
        config["scenario"]["network_scenarios"] = {"enable": True}
        config_path = self._write_config(tmp_path, config)

        with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            result = runner.invoke(main, ["validate", "-c", config_path])

        assert result.exit_code == 0, result.output
        logged = [str(call) for call in mock_logger.info.call_args_list]
        assert any("pod_scenarios, network_scenarios" in entry for entry in logged), (
            logged
        )

    def test_missing_config_path_fails(self):
        """Empty or non-existent config paths fail before any parsing"""
        runner = CliRunner()
        with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger

            result = runner.invoke(main, ["validate", "-c", ""])
            assert result.exit_code == 1
            assert "Config file invalid" in str(mock_logger.error.call_args)

            mock_logger.reset_mock()
            result = runner.invoke(main, ["validate", "-c", "/nonexistent.yaml"])
            assert result.exit_code == 1
            assert "Config file not found" in str(mock_logger.error.call_args)

    def test_malformed_yaml_fails_cleanly(self, tmp_path):
        """A YAML syntax error produces an error log, not a traceback"""
        runner = CliRunner()
        config_path = self._write_config(
            tmp_path, text="kubeconfig_file_path: [unclosed\n"
        )

        with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            result = runner.invoke(main, ["validate", "-c", config_path])

        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "not valid YAML" in str(mock_logger.error.call_args)

    def test_non_mapping_config_fails(self, tmp_path):
        """A YAML list at the top level is rejected"""
        runner = CliRunner()
        config_path = self._write_config(tmp_path, text="- just\n- a list\n")

        with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            result = runner.invoke(main, ["validate", "-c", config_path])

        assert result.exit_code == 1
        assert "must be a mapping" in str(mock_logger.error.call_args)

    def test_schema_error_reports_field_path(self, tmp_path):
        """Schema errors name the failing field and the reason"""
        runner = CliRunner()
        config = self._valid_config_dict()
        del config["fitness_function"]
        config["wait_duration"] = -5
        config_path = self._write_config(tmp_path, config)

        with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            result = runner.invoke(main, ["validate", "-c", config_path])

        assert result.exit_code == 1
        mock_logger.error.assert_called_once()
        template, count, details = mock_logger.error.call_args.args
        assert count == 2
        assert "fitness_function: Field required" in details
        assert "wait_duration: Input should be greater than or equal to 0" in details

    def test_no_enabled_scenarios_fails(self, tmp_path):
        """A schema-valid config with every scenario disabled is rejected"""
        runner = CliRunner()
        config = self._valid_config_dict()
        config["scenario"] = {"pod_scenarios": {"enable": False}}
        config_path = self._write_config(tmp_path, config)

        with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            result = runner.invoke(main, ["validate", "-c", config_path])

        assert result.exit_code == 1
        assert "No scenarios are enabled" in str(mock_logger.error.call_args)

    def test_params_are_applied(self, tmp_path):
        """-p values are substituted exactly as the run command does"""
        runner = CliRunner()
        config_path = self._write_config(tmp_path, self._valid_config_dict())

        with patch("krkn_ai.cli.cmd.read_config_from_file") as mock_read:
            mock_read.return_value = ConfigFile.model_validate(
                self._valid_config_dict()
            )
            result = runner.invoke(
                main, ["validate", "-c", config_path, "-p", "HOST=example.com"]
            )

        assert result.exit_code == 0, result.output
        mock_read.assert_called_once_with(config_path, ("HOST=example.com",), None)

    def test_bad_kubeconfig_override_is_rejected(self, tmp_path):
        """A -k path that does not exist fails instead of being silently ignored"""
        runner = CliRunner()
        config_path = self._write_config(tmp_path, self._valid_config_dict())

        with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            result = runner.invoke(
                main, ["validate", "-c", config_path, "-k", "/nonexistent/kubeconfig"]
            )

        assert result.exit_code == 1
        assert "Kubeconfig file not found" in str(mock_logger.error.call_args)

    def test_malformed_health_checks_with_params_reports_field(self, tmp_path):
        """A null health_checks section with -p is reported by pydantic, not a crash"""
        runner = CliRunner()
        config = self._valid_config_dict()
        config["health_checks"] = None
        config_path = self._write_config(tmp_path, config)

        with patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger:
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            result = runner.invoke(
                main, ["validate", "-c", config_path, "-p", "HOST=example.com"]
            )

        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)
        _, _, details = mock_logger.error.call_args.args
        assert details.startswith("  health_checks:")

    def test_check_connectivity_missing_kubeconfig_still_checks_prometheus(
        self, tmp_path
    ):
        """A missing kubeconfig fails the cluster check but Prometheus is still probed"""
        runner = CliRunner()
        config = self._valid_config_dict()
        config["kubeconfig_file_path"] = str(tmp_path / "missing-kubeconfig")
        config_path = self._write_config(tmp_path, config)

        with (
            patch("krkn_ai.cli.cmd.ClusterManager") as mock_cm,
            patch("krkn_ai.cli.cmd.create_prometheus_client") as mock_prom,
            patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger,
        ):
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            result = runner.invoke(
                main, ["validate", "-c", config_path, "--check-connectivity"]
            )

        assert result.exit_code == 1
        assert "kubeconfig file not found" in str(mock_logger.error.call_args)
        mock_cm.assert_not_called()
        mock_prom.assert_called_once()

    def test_check_connectivity_skips_prometheus_in_mock_mode(
        self, tmp_path, monkeypatch
    ):
        """MOCK_FITNESS would make the Prometheus probe a no-op, so it is reported as skipped"""
        runner = CliRunner()
        monkeypatch.setenv("MOCK_FITNESS", "true")
        kubeconfig_path = tmp_path / "kubeconfig"
        kubeconfig_path.write_text("apiVersion: v1\n")
        config_path = self._write_config(tmp_path, self._valid_config_dict())

        with (
            patch("krkn_ai.cli.cmd.ClusterManager"),
            patch("krkn_ai.cli.cmd.VersionApi"),
            patch("krkn_ai.cli.cmd.create_prometheus_client") as mock_prom,
            patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger,
        ):
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            result = runner.invoke(
                main,
                [
                    "validate",
                    "-c",
                    config_path,
                    "-k",
                    str(kubeconfig_path),
                    "--check-connectivity",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_prom.assert_not_called()
        assert "Prometheus check skipped" in str(mock_logger.warning.call_args)

    def test_check_connectivity_handles_library_exit(self, tmp_path):
        """krkn-lib exits the process on client init failure; validate reports it instead"""
        runner = CliRunner()
        kubeconfig_path = tmp_path / "kubeconfig"
        kubeconfig_path.write_text("apiVersion: v1\n")
        config_path = self._write_config(tmp_path, self._valid_config_dict())

        with (
            patch("krkn_ai.cli.cmd.ClusterManager"),
            patch("krkn_ai.cli.cmd.VersionApi"),
            patch("krkn_ai.cli.cmd.create_prometheus_client") as mock_prom,
            patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger,
        ):
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            mock_prom.side_effect = SystemExit(1)
            result = runner.invoke(
                main,
                [
                    "validate",
                    "-c",
                    config_path,
                    "-k",
                    str(kubeconfig_path),
                    "--check-connectivity",
                ],
            )

        assert result.exit_code == 1
        assert "client initialization failed" in str(mock_logger.error.call_args)

    def test_check_connectivity_succeeds(self, tmp_path):
        """--check-connectivity passes when cluster and Prometheus respond"""
        runner = CliRunner()
        kubeconfig_path = tmp_path / "kubeconfig"
        kubeconfig_path.write_text("apiVersion: v1\n")
        config_path = self._write_config(tmp_path, self._valid_config_dict())

        with (
            patch("krkn_ai.cli.cmd.ClusterManager") as mock_cm,
            patch("krkn_ai.cli.cmd.VersionApi") as mock_version_api,
            patch("krkn_ai.cli.cmd.create_prometheus_client") as mock_prom,
        ):
            result = runner.invoke(
                main,
                [
                    "validate",
                    "-c",
                    config_path,
                    "-k",
                    str(kubeconfig_path),
                    "--check-connectivity",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_cm.assert_called_once_with(str(kubeconfig_path))
        mock_version_api.assert_called_once_with(mock_cm.return_value.api_client)
        mock_version_api.return_value.get_code.assert_called_once()
        mock_prom.assert_called_once_with(str(kubeconfig_path))

    def test_check_connectivity_reports_both_failures(self, tmp_path):
        """Cluster and Prometheus are both checked even when the first fails"""
        runner = CliRunner()
        kubeconfig_path = tmp_path / "kubeconfig"
        kubeconfig_path.write_text("apiVersion: v1\n")
        config_path = self._write_config(tmp_path, self._valid_config_dict())

        with (
            patch("krkn_ai.cli.cmd.ClusterManager") as mock_cm,
            patch("krkn_ai.cli.cmd.create_prometheus_client") as mock_prom,
            patch("krkn_ai.cli.cmd.get_logger") as mock_get_logger,
        ):
            mock_logger = Mock()
            mock_get_logger.return_value = mock_logger
            mock_cm.side_effect = RuntimeError("connection refused")
            mock_prom.side_effect = PrometheusConnectionError("no prometheus")
            result = runner.invoke(
                main,
                [
                    "validate",
                    "-c",
                    config_path,
                    "-k",
                    str(kubeconfig_path),
                    "--check-connectivity",
                ],
            )

        assert result.exit_code == 1
        errors = " ".join(str(call) for call in mock_logger.error.call_args_list)
        assert "Cluster is not reachable" in errors
        assert "Prometheus is not reachable" in errors
        mock_prom.assert_called_once()
