"""
GenerationsReporter unit tests
"""

import os
import json
import yaml
import datetime

import pytest
from unittest.mock import patch

from krkn_ai.reporter.generations_reporter import GenerationsReporter
from krkn_ai.models.app import CommandRunResult, FitnessResult
from krkn_ai.models.scenario.base import BaseScenario, ScenarioOrigin
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.scenario.scenario_pod import PodScenario
from krkn_ai.models.cluster_components import ClusterComponents, Namespace, Pod


class TestGenerationsReporter:
    """Test GenerationsReporter core functionality"""

    def test_save_best_generations_yaml_format(self, temp_output_dir):
        """Test saving best generations in YAML format with multiple results"""
        reporter = GenerationsReporter(output_dir=temp_output_dir, format="yaml")
        scenario = DummyScenario(cluster_components=ClusterComponents())
        now = datetime.datetime.now()

        best_generations = [
            CommandRunResult(
                generation_id=0,
                scenario_id=1,
                scenario=scenario,
                cmd="test-cmd-1",
                log="log-1",
                returncode=0,
                start_time=now,
                end_time=now,
                fitness_result=FitnessResult(fitness_score=10.0),
            ),
            CommandRunResult(
                generation_id=1,
                scenario_id=2,
                scenario=scenario,
                cmd="test-cmd-2",
                log="log-2",
                returncode=0,
                start_time=now,
                end_time=now,
                fitness_result=FitnessResult(fitness_score=20.0),
            ),
        ]

        reporter.save_best_generations(best_generations)

        save_path = os.path.join(temp_output_dir, "reports", "best_scenarios.yaml")
        assert os.path.exists(save_path)

        with open(save_path, "r") as f:
            results = yaml.safe_load(f)
            assert len(results) == 2
            assert results[0]["generation_id"] == 0
            assert results[0]["fitness_result"]["fitness_score"] == 10.0
            assert "log" not in results[0]  # log should be removed
            assert results[1]["generation_id"] == 1
            assert results[1]["fitness_result"]["fitness_score"] == 20.0

    def test_save_best_generations_yaml_is_plain_yaml(self, temp_output_dir):
        """best_scenarios.yaml has no Python-specific tags, so safe_load reads it"""
        reporter = GenerationsReporter(output_dir=temp_output_dir, format="yaml")
        scenario = DummyScenario(cluster_components=ClusterComponents())
        scenario.origin = ScenarioOrigin.CROSSOVER
        start = datetime.datetime(2026, 11, 6, 10, 0, 0, 123456)

        reporter.save_best_generations(
            [
                CommandRunResult(
                    generation_id=1,
                    scenario_id=7,
                    scenario=scenario,
                    cmd="test-cmd",
                    log="test-log",
                    returncode=0,
                    start_time=start,
                    end_time=start,
                    fitness_result=FitnessResult(fitness_score=42.0),
                )
            ]
        )

        save_path = os.path.join(temp_output_dir, "reports", "best_scenarios.yaml")
        with open(save_path, "r") as f:
            content = f.read()
        assert "!!python" not in content

        results = yaml.safe_load(content)
        assert results[0]["scenario"]["origin"] == "crossover"
        assert results[0]["start_time"] == "2026-11-06T10:00:00.123456"
        assert "log" not in results[0]

    def test_save_best_generations_json_format(self, temp_output_dir):
        """Test saving best generations in JSON format"""
        reporter = GenerationsReporter(output_dir=temp_output_dir, format="json")
        scenario = DummyScenario(cluster_components=ClusterComponents())
        now = datetime.datetime.now()

        best_generations = [
            CommandRunResult(
                generation_id=0,
                scenario_id=1,
                scenario=scenario,
                cmd="test-cmd",
                log="test-log",
                returncode=0,
                start_time=now,
                end_time=now,
                fitness_result=FitnessResult(fitness_score=15.0),
            )
        ]

        reporter.save_best_generations(best_generations)

        save_path = os.path.join(temp_output_dir, "reports", "best_scenarios.json")
        assert os.path.exists(save_path)

        with open(save_path, "r") as f:
            results = json.load(f)
            assert len(results) == 1
            assert results[0]["generation_id"] == 0
            assert results[0]["fitness_result"]["fitness_score"] == 15.0

    def test_save_best_generation_graph_with_results(self, temp_output_dir):
        """Test generating best generation graph with valid data"""
        reporter = GenerationsReporter(output_dir=temp_output_dir, format="yaml")
        scenario = DummyScenario(cluster_components=ClusterComponents())
        now = datetime.datetime.now()

        best_generations = [
            CommandRunResult(
                generation_id=i,
                scenario_id=i + 1,
                scenario=scenario,
                cmd=f"cmd-{i}",
                log=f"log-{i}",
                returncode=0,
                start_time=now,
                end_time=now,
                fitness_result=FitnessResult(fitness_score=float(i * 10)),
            )
            for i in range(3)
        ]

        with patch("krkn_ai.reporter.generations_reporter.plt") as mock_plt:
            reporter.save_best_generation_graph(best_generations)

            mock_plt.savefig.assert_called_once()
            assert mock_plt.close.called

    def test_save_best_generation_graph_with_empty_list(self, temp_output_dir):
        """Test that empty list does not generate graph"""
        reporter = GenerationsReporter(output_dir=temp_output_dir, format="yaml")

        with patch("krkn_ai.reporter.generations_reporter.plt") as mock_plt:
            reporter.save_best_generation_graph([])

            # Should not call savefig for empty list
            mock_plt.savefig.assert_not_called()
            graph_path = os.path.join(
                temp_output_dir, "reports", "graphs", "best_generation.png"
            )
            assert not os.path.exists(graph_path)

    @pytest.mark.parametrize("fmt", ["yaml", "json"])
    def test_save_best_generations_includes_scenario_parameters(
        self, temp_output_dir, genetic_algorithm, fmt
    ):
        """Best-scenario and per-scenario reports preserve the same parameter values."""
        cluster = ClusterComponents(
            namespaces=[
                Namespace(
                    name="shop",
                    pods=[Pod(name="cart-0", labels={"app": "cart"})],
                )
            ]
        )
        scenario = PodScenario(cluster_components=cluster)
        now = datetime.datetime(2026, 11, 8, 12, 0, 0)
        run_result = CommandRunResult(
            generation_id=0,
            scenario_id=1,
            scenario=scenario,
            cmd="test-cmd",
            log="test-log",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=FitnessResult(fitness_score=25.0),
        )
        expected_params = [
            {"name": "namespace", "value": "shop"},
            {"name": "pod-label", "value": "app=cart"},
            {"name": "name-pattern", "value": ".*"},
            {"name": "disruption-count", "value": 1},
            {"name": "kill-timeout", "value": 60},
            {"name": "expected-recovery-time", "value": 60},
        ]

        self._assert_matching_report_parameters(
            genetic_algorithm, run_result, temp_output_dir, fmt, expected_params
        )

    @pytest.mark.parametrize("fmt", ["yaml", "json"])
    def test_save_best_generations_without_scenario_parameters(
        self, temp_output_dir, genetic_algorithm, mock_command_run_result, fmt
    ):
        mock_command_run_result.scenario = BaseScenario(
            name="base-scenario", krknctl_name="", krknhub_image=""
        )
        self._assert_matching_report_parameters(
            genetic_algorithm, mock_command_run_result, temp_output_dir, fmt, None
        )

    @staticmethod
    def _assert_matching_report_parameters(
        engine, run_result, output_dir, fmt, expected_params
    ):
        engine.format = fmt
        engine.save_scenario_result(run_result)
        reporter = GenerationsReporter(output_dir=output_dir, format=fmt)
        reporter.save_best_generations([run_result])
        loader = json.load if fmt == "json" else yaml.safe_load
        best_path = os.path.join(output_dir, "reports", f"best_scenarios.{fmt}")
        scenario_path = os.path.join(
            output_dir, fmt, "generation_0", f"scenario_1.{fmt}"
        )
        with open(best_path, encoding="utf-8") as f:
            best_result = loader(f)[0]
        with open(scenario_path, encoding="utf-8") as f:
            scenario_result = loader(f)

        assert best_result["scenario"]["name"] == run_result.scenario.name
        assert "log" not in best_result
        if expected_params is None:
            assert "parameters" not in best_result["scenario"]
            assert "parameters" not in scenario_result["scenario"]
        else:
            assert best_result["scenario"]["parameters"] == expected_params
            assert scenario_result["scenario"]["parameters"] == expected_params
