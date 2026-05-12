"""
JSONSummaryReporter unit tests
"""

import datetime

from krkn_ai.reporter.json_summary_reporter import JSONSummaryReporter
from krkn_ai.models.app import CommandRunResult, FitnessResult, FitnessScoreResult
from krkn_ai.models.config import ConfigFile, FitnessFunction, FitnessFunctionType, ScenarioConfig, PodScenarioConfig, HealthCheckResult
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.cluster_components import ClusterComponents


def _make_config():
    return ConfigFile(
        kubeconfig_file_path="/tmp/test",
        generations=5,
        population_size=4,
        fitness_function=FitnessFunction(query="q", type=FitnessFunctionType.point),
        scenario=ScenarioConfig(pod_scenarios=PodScenarioConfig(enable=True)),
        cluster_components=ClusterComponents(),
    )


def _make_scenario(end_value=10):
    """Create a DummyScenario with a unique end value for dict key uniqueness."""
    s = DummyScenario(cluster_components=ClusterComponents())
    s.end.value = end_value
    return s


def _make_result(
    generation_id=0,
    scenario_id=1,
    fitness_score=10.0,
    health_check_results=None,
    slo_scores=None,
    scenario=None,
):
    if scenario is None:
        scenario = _make_scenario(end_value=scenario_id)
    now = datetime.datetime.now(datetime.timezone.utc)
    scores = slo_scores or []
    return CommandRunResult(
        generation_id=generation_id,
        scenario_id=scenario_id,
        scenario=scenario,
        cmd="cmd",
        log="log",
        returncode=0,
        start_time=now,
        end_time=now,
        fitness_result=FitnessResult(fitness_score=fitness_score, scores=scores),
        health_check_results=health_check_results or {},
    )


class TestJSONSummaryReporterStoppingReason:
    def test_stopping_reason_included(self):
        config = _make_config()
        result = _make_result()
        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population={result.scenario: result},
            best_of_generation=[result],
            stopping_reason="Completed 5 generations",
        )
        summary = reporter.generate_summary()
        assert summary["stopping_reason"] == "Completed 5 generations"

    def test_stopping_reason_none_when_not_set(self):
        config = _make_config()
        result = _make_result()
        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population={result.scenario: result},
            best_of_generation=[result],
        )
        summary = reporter.generate_summary()
        assert summary["stopping_reason"] is None


class TestJSONSummaryReporterHealthCheckSummary:
    def test_health_check_summary_aggregates_across_scenarios(self):
        config = _make_config()
        s1 = _make_scenario(end_value=100)
        s2 = _make_scenario(end_value=200)
        r1 = _make_result(
            scenario_id=1,
            fitness_score=5.0,
            scenario=s1,
            health_check_results={
                "app1": [
                    HealthCheckResult(name="app1", response_time=0.1, status_code=200, success=True),
                    HealthCheckResult(name="app1", response_time=0.3, status_code=200, success=True),
                ]
            },
        )
        r2 = _make_result(
            scenario_id=2,
            fitness_score=8.0,
            scenario=s2,
            health_check_results={
                "app1": [
                    HealthCheckResult(name="app1", response_time=0.5, status_code=500, success=False),
                ]
            },
        )
        seen = {s1: r1, s2: r2}

        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population=seen,
            best_of_generation=[r2],
        )
        summary = reporter.generate_summary()
        hc = summary["health_check_summary"]
        assert hc is not None
        assert "app1" in hc
        assert hc["app1"]["min_response_time"] == 0.1
        assert hc["app1"]["max_response_time"] == 0.5
        assert hc["app1"]["total_checks"] == 3
        assert hc["app1"]["success_count"] == 2
        assert hc["app1"]["failure_count"] == 1
        assert hc["app1"]["success_rate"] == round(2 / 3, 4)

    def test_health_check_summary_none_when_no_data(self):
        config = _make_config()
        result = _make_result(health_check_results={})
        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population={result.scenario: result},
            best_of_generation=[result],
        )
        summary = reporter.generate_summary()
        assert summary["health_check_summary"] is None


class TestJSONSummaryReporterSLOBreakdown:
    def test_slo_breakdown_aggregates_per_id(self):
        config = _make_config()
        scores1 = [
            FitnessScoreResult(id=1, fitness_score=0.8, weighted_score=0.4),
            FitnessScoreResult(id=2, fitness_score=0.6, weighted_score=0.3),
        ]
        scores2 = [
            FitnessScoreResult(id=1, fitness_score=0.9, weighted_score=0.45),
            FitnessScoreResult(id=2, fitness_score=0.7, weighted_score=0.35),
        ]
        s1 = _make_scenario(end_value=100)
        s2 = _make_scenario(end_value=200)
        r1 = _make_result(scenario_id=1, fitness_score=5.0, slo_scores=scores1, scenario=s1)
        r2 = _make_result(scenario_id=2, fitness_score=8.0, slo_scores=scores2, scenario=s2)
        seen = {s1: r1, s2: r2}

        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population=seen,
            best_of_generation=[r2],
        )
        summary = reporter.generate_summary()
        slo = summary["slo_breakdown"]
        assert slo is not None
        assert "1" in slo
        assert "2" in slo
        assert slo["1"]["fitness_score"] == round((0.8 + 0.9) / 2, 4)
        assert slo["1"]["weighted_score"] == round((0.4 + 0.45) / 2, 4)
        assert slo["2"]["fitness_score"] == round((0.6 + 0.7) / 2, 4)
        assert slo["2"]["weighted_score"] == round((0.3 + 0.35) / 2, 4)

    def test_slo_breakdown_none_when_no_scores(self):
        config = _make_config()
        result = _make_result(slo_scores=[])
        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population={result.scenario: result},
            best_of_generation=[result],
        )
        summary = reporter.generate_summary()
        assert summary["slo_breakdown"] is None


class TestJSONSummaryReporterWorstScenarios:
    def test_worst_scenarios_returns_bottom_10(self):
        config = _make_config()
        results = {}
        for i in range(15):
            s = _make_scenario(end_value=i + 1)
            r = _make_result(scenario_id=i, fitness_score=float(i), scenario=s)
            results[s] = r

        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population=results,
            best_of_generation=[list(results.values())[-1]],
        )
        summary = reporter.generate_summary()
        worst = summary["worst_scenarios"]
        assert len(worst) == 10
        # Worst should be sorted ascending (lowest fitness first)
        assert worst[0]["fitness_score"] == 0.0
        assert worst[9]["fitness_score"] == 9.0
        assert worst[0]["rank"] == 1

    def test_worst_scenarios_empty_population(self):
        config = _make_config()
        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population={},
            best_of_generation=[],
        )
        summary = reporter.generate_summary()
        assert summary["worst_scenarios"] == []


class TestJSONSummaryReporterMinFitness:
    def test_min_fitness_score_included(self):
        config = _make_config()
        results = {}
        for i, score in enumerate([3.0, 1.5, 7.0]):
            s = _make_scenario(end_value=i + 1)
            r = _make_result(scenario_id=i, fitness_score=score, scenario=s)
            results[s] = r

        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population=results,
            best_of_generation=[list(results.values())[-1]],
        )
        summary = reporter.generate_summary()
        assert summary["summary"]["min_fitness_score"] == 1.5

    def test_min_fitness_score_zero_when_empty(self):
        config = _make_config()
        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population={},
            best_of_generation=[],
        )
        summary = reporter.generate_summary()
        assert summary["summary"]["min_fitness_score"] == 0.0


class TestJSONSummaryReporterSave:
    def test_save_writes_json_file(self, temp_output_dir):
        import json
        import os

        config = _make_config()
        result = _make_result()
        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=config,
            seen_population={result.scenario: result},
            best_of_generation=[result],
            stopping_reason="Completed 5 generations",
        )
        reporter.save(temp_output_dir)

        path = os.path.join(temp_output_dir, "results.json")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["stopping_reason"] == "Completed 5 generations"
        assert "health_check_summary" in data
        assert "slo_breakdown" in data
        assert "worst_scenarios" in data
        assert "min_fitness_score" in data["summary"]
