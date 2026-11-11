"""
KrknRunner core functionality tests
"""

import os
import datetime
import json
import pytest
from unittest.mock import Mock, patch

from krkn_ai.chaos_engines.krkn_runner import KRKN_HUB_FAILURE_SCORE, KrknRunner
from krkn_ai.chaos_engines.telemetry_parser import TelemetryResult
from krkn_ai.models.app import KrknRunnerType
from krkn_ai.models.config import (
    FitnessFunction,
    FitnessFunctionType,
    HealthCheckConfig,
)
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.scenario.base import CompositeScenario, CompositeDependency
from krkn_ai.models.cluster_components import ClusterComponents


class TestKrknRunnerInitialization:
    """Test KrknRunner initialization and runner type detection"""

    def test_init_with_explicit_runner_type(self, minimal_config, temp_output_dir):
        """Test initialization with explicit runner type"""
        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            assert runner.config == minimal_config
            assert runner.output_dir == temp_output_dir
            assert runner.runner_type == KrknRunnerType.CLI_RUNNER

    @patch("krkn_ai.chaos_engines.krkn_runner.run_shell")
    def test_init_detects_cli_runner(
        self, mock_run_shell, minimal_config, temp_output_dir
    ):
        """Test automatic detection of CLI runner when krknctl is available"""
        mock_run_shell.side_effect = [
            ("krknctl version 1.0.0", 0),  # krknctl available
            ("podman version 1.0.0", 0),  # podman also available
        ]
        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(config=minimal_config, output_dir=temp_output_dir)
            assert runner.runner_type == KrknRunnerType.CLI_RUNNER

    @patch("krkn_ai.chaos_engines.krkn_runner.run_shell")
    def test_init_raises_when_no_runner_available(
        self, mock_run_shell, minimal_config, temp_output_dir
    ):
        """Test raises exception when neither krknctl nor podman is available"""
        mock_run_shell.side_effect = [
            ("", 1),  # krknctl not available
            ("", 1),  # podman not available
        ]
        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            with pytest.raises(Exception, match="krknctl and podman are not available"):
                KrknRunner(config=minimal_config, output_dir=temp_output_dir)

    def test_operator_runner_rejects_composite_generation(
        self, minimal_config, temp_output_dir
    ):
        minimal_config.genetic.composition_rate = 0.5

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            with pytest.raises(ValueError, match="composition_rate"):
                KrknRunner(
                    config=minimal_config,
                    output_dir=temp_output_dir,
                    runner_type=KrknRunnerType.OPERATOR_RUNNER,
                )

    def test_mocked_operator_runner_does_not_initialize_executor(
        self, minimal_config, temp_output_dir
    ):
        with (
            patch(
                "krkn_ai.chaos_engines.krkn_runner.is_mock_enabled",
                return_value=True,
            ),
            patch("krkn_ai.chaos_engines.krkn_runner.OperatorExecutor") as executor,
        ):
            KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.OPERATOR_RUNNER,
            )

        executor.assert_not_called()


class TestKrknRunnerRun:
    """Test KrknRunner.run method core behavior"""

    def test_run_scenario_with_mock_mode(self, minimal_config, temp_output_dir):
        """Test running scenario in mock mode returns successful result"""
        minimal_config.fitness_function = FitnessFunction(
            query="test_query", type=FitnessFunctionType.point
        )
        minimal_config.health_checks = HealthCheckConfig()

        with patch.dict(os.environ, {"MOCK": "true"}):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            scenario = DummyScenario(cluster_components=ClusterComponents())

            result = runner.run(scenario, generation_id=0)

            assert result.generation_id == 0
            assert result.scenario == scenario
            assert result.returncode == 0
            assert isinstance(result.start_time, datetime.datetime)
            assert isinstance(result.end_time, datetime.datetime)

    @patch("krkn_ai.chaos_engines.krkn_runner.is_mock_enabled", return_value=False)
    @patch("krkn_ai.chaos_engines.krkn_runner.run_shell")
    def test_run_handles_misconfiguration_failure(
        self, mock_run_shell, mock_env, minimal_config, temp_output_dir
    ):
        """Test run handles misconfiguration failure (non-zero, non-2 return code)"""
        minimal_config.fitness_function = FitnessFunction(
            query="test_query",
            type=FitnessFunctionType.point,
            include_krkn_failure=True,
        )
        minimal_config.health_checks = HealthCheckConfig()

        # Simulate misconfiguration failure (return code 1)
        mock_run_shell.return_value = ("error log", 1)

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            with patch(
                "krkn_ai.chaos_engines.krkn_runner.extract_telemetry_from_log",
                return_value=TelemetryResult(exit_status=1),
            ):
                runner = KrknRunner(
                    config=minimal_config,
                    output_dir=temp_output_dir,
                    runner_type=KrknRunnerType.CLI_RUNNER,
                )
                scenario = DummyScenario(cluster_components=ClusterComponents())

                result = runner.run(scenario, generation_id=0)

                assert result.returncode == 1
                assert result.fitness_result.fitness_score == -1.0
                assert result.fitness_result.krkn_failure_score == -1.0

    def test_operator_terminal_failure_cannot_be_masked_by_telemetry(
        self, minimal_config, temp_output_dir
    ):
        minimal_config.health_checks = HealthCheckConfig()

        with (
            patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"),
            patch(
                "krkn_ai.chaos_engines.krkn_runner.HealthCheckWatcher"
            ) as health_check_watcher,
            patch(
                "krkn_ai.chaos_engines.krkn_runner.extract_telemetry_from_log",
                return_value=TelemetryResult(exit_status=0),
            ),
        ):
            health_check_watcher.return_value.get_results.return_value = {}
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.OPERATOR_RUNNER,
            )
            runner._operator_executor = Mock()
            runner._operator_executor.execute.return_value = ("scenario log", 1, None)

            result = runner.run(
                DummyScenario(cluster_components=ClusterComponents()),
                generation_id=0,
            )

        assert result.returncode == 1

    def test_cancelled_operator_execution_still_collects_raw_fitness(
        self, minimal_config, temp_output_dir
    ):
        minimal_config.health_checks = HealthCheckConfig()
        with (
            patch(
                "krkn_ai.chaos_engines.krkn_runner.is_mock_enabled", return_value=False
            ),
            patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"),
            patch("krkn_ai.chaos_engines.krkn_runner.HealthCheckWatcher") as watcher,
            patch(
                "krkn_ai.chaos_engines.krkn_runner.extract_telemetry_from_log",
                return_value=TelemetryResult(exit_status=1),
            ),
        ):
            watcher.return_value.get_results.return_value = {}
            runner = KrknRunner(
                minimal_config,
                temp_output_dir,
                KrknRunnerType.OPERATOR_RUNNER,
            )
            raw_fitness = Mock(return_value=4.0)
            runner.fitness_calculator.calculate_fitness_value = raw_fitness
            runner._operator_executor = Mock()
            runner._operator_executor.execute.return_value = (
                "partial scenario log",
                1,
                "cancelled",
            )

            result = runner.run(
                DummyScenario(cluster_components=ClusterComponents()), 0
            )

        assert result.outcome == "cancelled"
        assert result.returncode == 1
        assert len(result.fitness_result.scores) == 1
        assert result.fitness_result.scores[0].fitness_score == 4.0
        assert result.fitness_result.scores[0].normalized_score is None

    @pytest.mark.parametrize("resiliency_score", [100, 20])
    @pytest.mark.parametrize("exit_status", [1, 2])
    @pytest.mark.parametrize(
        "runner_type", [KrknRunnerType.CLI_RUNNER, KrknRunnerType.OPERATOR_RUNNER]
    )
    def test_recovery_failure_scores_even_when_slos_pass(
        self,
        minimal_config,
        temp_output_dir,
        runner_type,
        resiliency_score,
        exit_status,
    ):
        minimal_config.fitness_function = FitnessFunction(
            query="up",
            include_krkn_failure=True,
            include_health_check_failure=False,
            include_health_check_response_time=False,
        )
        minimal_config.health_checks = HealthCheckConfig()
        log = "Chaos data:" + json.dumps(
            {
                "telemetry": {
                    "scenarios": [
                        {
                            "exit_status": exit_status,
                            "affected_pods": {
                                "unrecovered": (
                                    [{"pod_name": "shipping"}]
                                    if exit_status == 1
                                    else []
                                ),
                                "error": None,
                            },
                        }
                    ],
                    "error_logs": [],
                    "overall_resiliency_report": {"resiliency_score": resiliency_score},
                }
            }
        )
        with (
            patch(
                "krkn_ai.chaos_engines.krkn_runner.is_mock_enabled", return_value=False
            ),
            patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"),
            patch("krkn_ai.chaos_engines.krkn_runner.HealthCheckWatcher") as watcher,
            patch(
                "krkn_ai.chaos_engines.krkn_runner.run_shell",
                return_value=(log, exit_status),
            ),
        ):
            watcher.return_value.get_results.return_value = {}
            runner = KrknRunner(minimal_config, temp_output_dir, runner_type)
            runner.fitness_calculator.calculate_fitness_value = Mock(return_value=0.0)
            runner._operator_executor = Mock()
            runner._operator_executor.execute.return_value = (log, exit_status, None)
            result = runner.run(
                DummyScenario(cluster_components=ClusterComponents()), 0
            )

        assert result.returncode == exit_status
        assert result.resiliency_score == resiliency_score
        assert result.fitness_result.krkn_failure_score == KRKN_HUB_FAILURE_SCORE
        assert result.fitness_result.fitness_score == KRKN_HUB_FAILURE_SCORE / 2 * 100

    @pytest.mark.parametrize(
        "log, expected_returncode, expected_score",
        [
            # krknctl graph run exits 0 even when a node fails; a scored run
            # is the mocked fitness value (10.5) scaled by 100
            ("EXITING 0\n", 0, 1050.0),
            (
                "scenario b at step 1 with exit status 1, check log file b-1.log.\n",
                1,
                -1.0,
            ),
            (
                "scenario b at step 1 with exit status 2, check log file b-1.log.\n",
                2,
                1050.0,
            ),
        ],
    )
    def test_composite_run_uses_node_exit_status(
        self,
        minimal_config,
        temp_output_dir,
        monkeypatch,
        tmp_path,
        log,
        expected_returncode,
        expected_score,
    ):
        monkeypatch.chdir(tmp_path)
        minimal_config.fitness_function = FitnessFunction(
            query="up",
            include_krkn_failure=False,
            include_health_check_failure=False,
            include_health_check_response_time=False,
        )
        minimal_config.health_checks = HealthCheckConfig()
        composite = CompositeScenario(
            scenario_a=DummyScenario(cluster_components=ClusterComponents()),
            scenario_b=DummyScenario(cluster_components=ClusterComponents()),
            dependency=CompositeDependency.NONE,
        )
        with (
            patch(
                "krkn_ai.chaos_engines.krkn_runner.is_mock_enabled", return_value=False
            ),
            patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"),
            patch("krkn_ai.chaos_engines.krkn_runner.HealthCheckWatcher") as watcher,
            patch(
                "krkn_ai.chaos_engines.krkn_runner.run_shell",
                return_value=(log, 0),
            ),
        ):
            watcher.return_value.get_results.return_value = {}
            runner = KrknRunner(
                minimal_config, temp_output_dir, KrknRunnerType.CLI_RUNNER
            )
            runner.fitness_calculator.calculate_fitness_value = Mock(return_value=10.5)
            result = runner.run(composite, 0)

        assert result.returncode == expected_returncode
        assert result.fitness_result.fitness_score == expected_score

    def test_composite_recovery_failure_is_scored_not_misconfiguration(
        self, minimal_config, temp_output_dir, monkeypatch, tmp_path
    ):
        """A node that exits 1 with unrecovered targets in its own log is a real
        chaos result, as it is for a single scenario."""
        monkeypatch.chdir(tmp_path)
        node_log = "Chaos data:" + json.dumps(
            {
                "telemetry": {
                    "scenarios": [
                        {
                            "exit_status": 1,
                            "affected_pods": {
                                "unrecovered": [{"pod_name": "shipping"}],
                                "error": None,
                            },
                        }
                    ],
                    "error_logs": [],
                }
            }
        )
        minimal_config.fitness_function = FitnessFunction(
            query="up",
            include_krkn_failure=True,
            include_health_check_failure=False,
            include_health_check_response_time=False,
        )
        minimal_config.health_checks = HealthCheckConfig()
        composite = CompositeScenario(
            scenario_a=DummyScenario(cluster_components=ClusterComponents()),
            scenario_b=DummyScenario(cluster_components=ClusterComponents()),
            dependency=CompositeDependency.NONE,
        )
        log = "scenario b at step 1 with exit status 1, check log file b-1.log.\n"

        def fake_run_shell(command, **kwargs):
            # krknctl writes the node log into the directory it runs in
            with open(os.path.join(kwargs["cwd"], "b-1.log"), "w") as f:
                f.write(node_log)
            return log, 0

        with (
            patch(
                "krkn_ai.chaos_engines.krkn_runner.is_mock_enabled", return_value=False
            ),
            patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"),
            patch("krkn_ai.chaos_engines.krkn_runner.HealthCheckWatcher") as watcher,
            patch(
                "krkn_ai.chaos_engines.krkn_runner.run_shell",
                side_effect=fake_run_shell,
            ),
        ):
            watcher.return_value.get_results.return_value = {}
            runner = KrknRunner(
                minimal_config, temp_output_dir, KrknRunnerType.CLI_RUNNER
            )
            runner.fitness_calculator.calculate_fitness_value = Mock(return_value=0.0)
            result = runner.run(composite, 0)

        assert result.returncode == 1
        assert result.fitness_result.krkn_failure_score == KRKN_HUB_FAILURE_SCORE
        assert result.fitness_result.fitness_score == KRKN_HUB_FAILURE_SCORE / 2 * 100

    def test_composite_node_logs_go_to_a_directory_per_run(
        self, minimal_config, temp_output_dir, monkeypatch, tmp_path
    ):
        """krknctl writes each node's log to its working directory, so each
        graph run gets its own directory under the output dir, its node logs
        are read from there, and the saved log says where they are (#160)."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        minimal_config.fitness_function = FitnessFunction(
            query="up",
            include_krkn_failure=True,
            include_health_check_failure=False,
            include_health_check_response_time=False,
        )
        minimal_config.health_checks = HealthCheckConfig()
        composite = CompositeScenario(
            scenario_a=DummyScenario(cluster_components=ClusterComponents()),
            scenario_b=DummyScenario(cluster_components=ClusterComponents()),
            dependency=CompositeDependency.NONE,
        )
        node_log = "Chaos data:" + json.dumps(
            {
                "telemetry": {
                    "scenarios": [
                        {
                            "exit_status": 1,
                            "affected_pods": {
                                "unrecovered": [{"pod_name": "shipping"}],
                                "error": None,
                            },
                        }
                    ],
                    "error_logs": [],
                }
            }
        )
        calls = []

        def fake_run_shell(command, **kwargs):
            calls.append(kwargs)
            with open(os.path.join(kwargs["cwd"], "b-1.log"), "w") as f:
                f.write(node_log)
            return (
                "scenario b at step 1 with exit status 1, check log file b-1.log.\n",
                0,
            )

        with (
            patch(
                "krkn_ai.chaos_engines.krkn_runner.is_mock_enabled", return_value=False
            ),
            patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"),
            patch("krkn_ai.chaos_engines.krkn_runner.HealthCheckWatcher") as watcher,
            patch(
                "krkn_ai.chaos_engines.krkn_runner.run_shell",
                side_effect=fake_run_shell,
            ),
        ):
            watcher.return_value.get_results.return_value = {}
            runner = KrknRunner(
                minimal_config, temp_output_dir, KrknRunnerType.CLI_RUNNER
            )
            runner.fitness_calculator.calculate_fitness_value = Mock(return_value=0.0)
            result = runner.run(composite, 3, scenario_id=7)

        run_dir = calls[0]["cwd"]
        assert os.path.isabs(run_dir)
        assert os.path.realpath(run_dir) == os.path.realpath(
            os.path.join(temp_output_dir, "graph_logs", "3_7")
        )
        assert os.path.isfile(os.path.join(run_dir, "b-1.log"))
        assert not os.listdir(elsewhere)
        assert result.returncode == 1
        assert result.fitness_result.krkn_failure_score == KRKN_HUB_FAILURE_SCORE
        assert run_dir in result.log

    def test_run_raises_for_unsupported_scenario_type(
        self, minimal_config, temp_output_dir
    ):
        """Test run raises NotImplementedError for unsupported scenario type"""
        minimal_config.health_checks = HealthCheckConfig()

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            unsupported_scenario = Mock()  # Not a Scenario or CompositeScenario

            with pytest.raises(NotImplementedError, match="Scenario unable to run"):
                runner.run(unsupported_scenario, generation_id=0)


class TestKrknRunnerCommandGeneration:
    """Test command generation methods"""

    def test_runner_command_for_cli_runner(self, minimal_config, temp_output_dir):
        """Test runner_command generates correct CLI command format"""
        minimal_config.wait_duration = 60
        minimal_config.kubeconfig_file_path = "/tmp/kubeconfig"

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            scenario = DummyScenario(cluster_components=ClusterComponents())

            command = runner.runner_command(scenario)

            assert "krknctl run" in command
            assert "dummy-scenario" in command
            assert "--wait-duration 60" in command
            assert "/tmp/kubeconfig" in command

    def test_runner_command_for_hub_runner(self, minimal_config, temp_output_dir):
        """Test runner_command generates correct podman command format"""
        minimal_config.wait_duration = 60
        minimal_config.kubeconfig_file_path = "/tmp/kubeconfig"

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.HUB_RUNNER,
            )
            scenario = DummyScenario(cluster_components=ClusterComponents())

            command = runner.runner_command(scenario)

            assert "podman run" in command
            assert "dummy-scenario" in command
            assert "--net=host" in command
            assert "/tmp/kubeconfig" in command

    def test_graph_command_uses_absolute_paths(self, monkeypatch, tmp_path):
        """krknctl runs in the graph log directory, so relative paths from the
        CLI (-k ./tmp/kubeconfig.yaml, -o ./tmp/results) must be made absolute."""
        import shlex
        from krkn_ai.chaos_engines.composite import build_graph_command

        monkeypatch.chdir(tmp_path)
        composite = CompositeScenario(
            scenario_a=DummyScenario(cluster_components=ClusterComponents()),
            scenario_b=DummyScenario(cluster_components=ClusterComponents()),
            dependency=CompositeDependency.NONE,
        )
        args = shlex.split(
            build_graph_command(composite, "./tmp/kubeconfig.yaml", "./tmp/results")
        )
        graph_file = args[3]
        kubeconfig = args[args.index("--kubeconfig") + 1]
        assert os.path.isabs(graph_file) and os.path.isfile(graph_file)
        assert kubeconfig == str(tmp_path / "tmp" / "kubeconfig.yaml")

    def test_graph_command_paths_survive_spaces_and_home(self, monkeypatch, tmp_path):
        import shlex
        from krkn_ai.chaos_engines.composite import build_graph_command

        work = tmp_path / "a b"
        work.mkdir()
        monkeypatch.chdir(work)
        monkeypatch.setenv("HOME", str(tmp_path / "home dir"))
        composite = CompositeScenario(
            scenario_a=DummyScenario(cluster_components=ClusterComponents()),
            scenario_b=DummyScenario(cluster_components=ClusterComponents()),
            dependency=CompositeDependency.NONE,
        )
        args = shlex.split(build_graph_command(composite, "~/.kube/config", "./out"))
        assert len(args) == 6
        assert os.path.isfile(args[3])
        assert args[5] == str(tmp_path / "home dir" / ".kube" / "config")

    @patch("krkn_ai.chaos_engines.krkn_runner.is_mock_enabled", return_value=False)
    @patch("krkn_ai.chaos_engines.krkn_runner.run_shell", return_value=("", 0))
    def test_single_scenario_runs_in_the_process_directory(
        self, mock_run_shell, mock_env, minimal_config, temp_output_dir
    ):
        minimal_config.health_checks = HealthCheckConfig()
        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.run(DummyScenario(cluster_components=ClusterComponents()), 0)
        assert mock_run_shell.call_args.kwargs["cwd"] is None
        assert not os.path.exists(os.path.join(temp_output_dir, "graph_logs"))

    def test_graph_command_creates_json_file(self, minimal_config, temp_output_dir):
        """Test graph_command creates JSON file for composite scenario"""
        minimal_config.kubeconfig_file_path = "/tmp/kubeconfig"

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            scenario_a = DummyScenario(cluster_components=ClusterComponents())
            scenario_b = DummyScenario(cluster_components=ClusterComponents())
            composite = CompositeScenario(
                scenario_a=scenario_a,
                scenario_b=scenario_b,
                dependency=CompositeDependency.NONE,
            )

            command = runner.graph_command(composite)

            assert "krknctl graph run" in command
            assert "/tmp/kubeconfig" in command
            # Verify JSON file was created
            graph_dir = os.path.join(temp_output_dir, "graphs")
            assert os.path.exists(graph_dir)
            json_files = [f for f in os.listdir(graph_dir) if f.endswith(".json")]
            assert len(json_files) > 0
