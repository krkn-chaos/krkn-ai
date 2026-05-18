"""
Unit tests for JSONSummaryReporter
"""

import os
import json
import datetime

from krkn_ai.reporter.json_summary_reporter import JSONSummaryReporter
from krkn_ai.models.app import CommandRunResult, FitnessResult
from krkn_ai.models.scenario.scenario_dummy import DummyScenario


class TestJSONSummaryReporter:
    """Test JSONSummaryReporter core functionality"""

    def _create_results(self, gen_id, start_score, count, scenario, now):
        results = {}
        for i in range(count):
            sid = (gen_id * 100) + i
            score = float(start_score + (i * 10))
            res = CommandRunResult(
                generation_id=gen_id,
                scenario_id=sid,
                scenario=scenario,
                cmd="test",
                log="test",
                returncode=0,
                start_time=now,
                end_time=now,
                fitness_result=FitnessResult(fitness_score=score),
            )
            results[sid] = res
        return results

    def test_generate_summary_content(self, minimal_config):
        """Test summary dictionary content and calculations"""
        now = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        cc = minimal_config.cluster_components
        scenario = DummyScenario(cluster_components=cc)
        
        gen0 = self._create_results(0, 0, 3, scenario, now)
        gen1 = self._create_results(1, 40, 3, scenario, now)
        
        pop = {**gen0, **gen1}
        best = [gen0[2], gen1[102]]

        reporter = JSONSummaryReporter(
            run_uuid="test-run",
            config=minimal_config,
            seen_population=pop,
            best_of_generation=best,
            start_time=now,
            end_time=now + datetime.timedelta(seconds=100),
            completed_generations=2,
            seed=123
        )
        
        summary = reporter.generate_summary()

        assert summary["run_id"] == "test-run"
        assert summary["seed"] == 123
        assert summary["start_time"] == now.isoformat()
        assert summary["duration_seconds"] == 100.0
        
        assert summary["config"]["generations"] == minimal_config.generations
        assert summary["config"]["population_size"] == minimal_config.population_size
        
        assert summary["summary"]["total_scenarios_executed"] == 6
        assert summary["summary"]["best_fitness_score"] == 60.0
        assert summary["summary"]["average_fitness_score"] == 30.0
        assert summary["summary"]["generations_completed"] == 2
        
        assert len(summary["fitness_progression"]) == 2
        assert summary["fitness_progression"][0]["average"] == 10.0
        assert summary["fitness_progression"][0]["best"] == 20.0
        assert summary["fitness_progression"][1]["average"] == 50.0
        assert summary["fitness_progression"][1]["best"] == 60.0

    def test_best_scenarios_ranking(self, minimal_config):
        """Test ranking logic and top 10 truncation"""
        now = datetime.datetime.now(datetime.timezone.utc)
        cc = minimal_config.cluster_components
        scenario = DummyScenario(cluster_components=cc)
        
        pop = self._create_results(0, 0, 15, scenario, now)
        
        reporter = JSONSummaryReporter(
            run_uuid="test",
            config=minimal_config,
            seen_population=pop,
            best_of_generation=[],
        )
        
        best = reporter.generate_summary()["best_scenarios"]
        assert len(best) == 10
        
        for i in range(10):
            item = best[i]
            assert item["rank"] == i + 1
            expected_score = float(140 - (i * 10))
            assert item["fitness_score"] == expected_score
            assert "scenario_id" in item
            assert "generation" in item
            assert "scenario_type" in item
            assert "parameters" in item

    def test_edge_cases(self, minimal_config):
        """Test single generation and zero fitness cases"""
        now = datetime.datetime.now(datetime.timezone.utc)
        cc = minimal_config.cluster_components
        scenario = DummyScenario(cluster_components=cc)

        gen0 = self._create_results(0, 50, 2, scenario, now)
        reporter = JSONSummaryReporter(
            run_uuid="single",
            config=minimal_config,
            seen_population=gen0,
            best_of_generation=[gen0[1]],
            completed_generations=1
        )
        summary = reporter.generate_summary()
        assert len(summary["fitness_progression"]) == 1
        assert summary["fitness_progression"][0]["best"] == 60.0

        res_zero = CommandRunResult(
            generation_id=0,
            scenario_id=999,
            scenario=scenario,
            cmd="test",
            log="test",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=FitnessResult(fitness_score=0.0),
        )
        reporter = JSONSummaryReporter(
            run_uuid="zero",
            config=minimal_config,
            seen_population={999: res_zero},
            best_of_generation=[],
        )
        summary = reporter.generate_summary()
        assert summary["summary"]["best_fitness_score"] == 0.0
        assert summary["summary"]["average_fitness_score"] == 0.0

    def test_empty_population(self, minimal_config):
        """Test summary behavior with no results"""
        reporter = JSONSummaryReporter(
            run_uuid="empty",
            config=minimal_config,
            seen_population={},
            best_of_generation=[],
        )
        summary = reporter.generate_summary()
        assert summary["summary"]["total_scenarios_executed"] == 0
        assert summary["best_scenarios"] == []
        assert summary["summary"]["best_fitness_score"] == 0.0
        assert summary["summary"]["average_fitness_score"] == 0.0

    def test_save_json_consistency(self, minimal_config, temp_output_dir):
        """Test that save method output matches generated summary"""
        now = datetime.datetime.now(datetime.timezone.utc)
        cc = minimal_config.cluster_components
        scenario = DummyScenario(cluster_components=cc)
        pop = self._create_results(0, 10, 1, scenario, now)

        reporter = JSONSummaryReporter(
            run_uuid="save-test",
            config=minimal_config,
            seen_population=pop,
            best_of_generation=[],
        )
        
        expected_summary = reporter.generate_summary()
        reporter.save(temp_output_dir)
        
        path = os.path.join(temp_output_dir, "results.json")
        assert os.path.exists(path)
        with open(path, "r") as f:
            saved_content = json.load(f)
            assert saved_content == expected_summary
