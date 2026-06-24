"""
Tests that per-generation average fitness in fitness_progression is computed
correctly when scenarios repeat across generations (cache hits).

Regression test for:
  Bug: _build_fitness_progression() used seen_population.values() filtered by
  generation_id, but seen_population only stores results with the generation_id
  from the *first* run.  Cache-hit copies returned by calculate_fitness() carry
  the corrected generation_id but were never reflected in seen_population, so
  later generations showed artificially low (or zero) averages.

Fix: GeneticAlgorithm now accumulates every result (fresh + cache) in
  all_evaluated_results and passes that list to JSONSummaryReporter, which uses
  it instead of seen_population.values() for per-generation average calculation.
"""

import datetime


from krkn_ai.models.app import CommandRunResult, FitnessResult
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.reporter.json_summary_reporter import JSONSummaryReporter


def _make_result(generation_id: int, fitness_score: float, scenario_id: int, scenario):
    now = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
    return CommandRunResult(
        generation_id=generation_id,
        scenario_id=scenario_id,
        scenario=scenario,
        cmd="test",
        log="",
        returncode=0,
        start_time=now,
        end_time=now,
        fitness_result=FitnessResult(fitness_score=fitness_score),
    )


class TestFitnessProgressionCacheCorrectness:
    """
    Verify that per-generation average fitness accounts for cache-hit
    (repeated) scenarios, not just first-time scenario evaluations.
    """

    def test_per_generation_average_includes_cache_hits(self, minimal_config):
        """
        Scenario repeated in generation 1 must be counted in generation 1's
        average, even though seen_population stores it with generation_id=0.
        """
        scenario = DummyScenario(cluster_components=ClusterComponents())

        # Generation 0: scenario evaluated fresh, fitness=10.0
        gen0_result = _make_result(
            generation_id=0, fitness_score=10.0, scenario_id=1, scenario=scenario
        )

        # seen_population stores only the first-run result (generation_id=0)
        seen_population = {scenario: gen0_result}

        # Generation 1: same scenario reappears as a cache hit.
        # calculate_fitness() deep-copies and sets generation_id=1.
        gen1_cache_hit = _make_result(
            generation_id=1, fitness_score=10.0, scenario_id=1, scenario=scenario
        )
        # Generation 1 also has a fresh scenario with fitness=30.0
        scenario2 = DummyScenario(cluster_components=ClusterComponents())
        gen1_fresh = _make_result(
            generation_id=1, fitness_score=30.0, scenario_id=2, scenario=scenario2
        )
        seen_population[scenario2] = gen1_fresh

        # all_evaluated_results mirrors what GeneticAlgorithm.calculate_fitness()
        # produces: gen0 fresh + gen1 cache-hit copy + gen1 fresh.
        all_evaluated_results = [gen0_result, gen1_cache_hit, gen1_fresh]

        # best_of_generation = one entry per generation (gen0 best, gen1 best)
        best_of_generation = [gen0_result, gen1_fresh]

        reporter = JSONSummaryReporter(
            run_uuid="test-cache",
            config=minimal_config,
            seen_population=seen_population,
            best_of_generation=best_of_generation,
            all_evaluated_results=all_evaluated_results,
        )

        summary = reporter.generate_summary()
        progression = summary["fitness_progression"]

        assert len(progression) == 2

        # Generation 0: only gen0_result → average = 10.0
        assert progression[0]["generation"] == 0
        assert progression[0]["average"] == 10.0

        # Generation 1: gen1_cache_hit (10.0) + gen1_fresh (30.0) → average = 20.0
        # Without the fix this would be 30.0 (only gen1_fresh counted) because
        # gen1_cache_hit's generation_id=1 is invisible to seen_population filter.
        assert progression[1]["generation"] == 1
        assert progression[1]["average"] == 20.0

    def test_backward_compat_without_all_evaluated_results(self, minimal_config):
        """
        When all_evaluated_results is not provided (old callers), the reporter
        falls back to seen_population.values() and still works correctly.
        """
        scenario = DummyScenario(cluster_components=ClusterComponents())
        gen0_result = _make_result(
            generation_id=0, fitness_score=50.0, scenario_id=1, scenario=scenario
        )
        seen_population = {scenario: gen0_result}
        best_of_generation = [gen0_result]

        reporter = JSONSummaryReporter(
            run_uuid="compat",
            config=minimal_config,
            seen_population=seen_population,
            best_of_generation=best_of_generation,
            # all_evaluated_results intentionally omitted
        )
        summary = reporter.generate_summary()
        assert summary["fitness_progression"][0]["average"] == 50.0

    def test_no_cache_hits_results_unchanged(self, minimal_config):
        """
        When every scenario is unique (no cache hits), all_evaluated_results
        equals seen_population.values() and averages must be identical.
        """
        cc = minimal_config.cluster_components

        s1 = DummyScenario(cluster_components=cc)
        s2 = DummyScenario(cluster_components=cc)

        r1 = _make_result(
            generation_id=0, fitness_score=20.0, scenario_id=1, scenario=s1
        )
        r2 = _make_result(
            generation_id=1, fitness_score=40.0, scenario_id=2, scenario=s2
        )

        seen_population = {s1: r1, s2: r2}
        all_evaluated_results = [r1, r2]
        best_of_generation = [r1, r2]

        reporter = JSONSummaryReporter(
            run_uuid="no-cache",
            config=minimal_config,
            seen_population=seen_population,
            best_of_generation=best_of_generation,
            all_evaluated_results=all_evaluated_results,
        )
        summary = reporter.generate_summary()
        assert summary["fitness_progression"][0]["average"] == 20.0
        assert summary["fitness_progression"][1]["average"] == 40.0
