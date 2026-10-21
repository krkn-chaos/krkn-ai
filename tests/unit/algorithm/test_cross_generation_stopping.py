"""
Stopping criteria and adaptive mutation compare generations on one scale
"""

import datetime

import pytest

from krkn_ai.models.app import CommandRunResult, FitnessResult, FitnessScoreResult
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.config import FitnessFunctionItem
from krkn_ai.models.scenario.scenario_dummy import DummyScenario


def _run_with_scores(engine, monkeypatch, growth):
    """Run simulate() where the raw SLO score of every scenario is multiplied by
    ``growth`` in each generation."""
    engine.config.baseline.enable = False
    engine.config.fitness_function.items = [FitnessFunctionItem(id=1, query="q")]
    engine.algo_config.population_size = 2
    engine.algo_config.generations = 4
    engine.algo_config.crossover_rate = 0.0
    engine.algo_config.mutation_rate = 0.0
    engine.algo_config.composition_rate = 0.0
    engine.algo_config.population_injection_rate = 0.0
    engine.algo_config.stopping_criteria.generation_saturation = 1
    engine.current_scenario_mutation_rate = 0.0
    parents = [DummyScenario(cluster_components=ClusterComponents()) for _ in range(2)]
    parents[0].end.value = 10
    parents[1].end.value = 20
    monkeypatch.setattr(engine, "create_population", lambda size: parents)
    monkeypatch.setattr(
        engine, "select_parents", lambda results: tuple(r.scenario for r in results)
    )
    # Children are copies of their parents; skip the seen_population cache so
    # each generation is evaluated again with its own scores.
    monkeypatch.setattr(engine, "calculate_fitness", engine.evaluate_scenario)

    def evaluate(scenario, generation):
        now = datetime.datetime.now(datetime.timezone.utc)
        raw = float(scenario.end.value) * growth**generation
        return CommandRunResult(
            generation_id=generation,
            scenario=scenario,
            cmd="",
            log="",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=FitnessResult(
                scores=[FitnessScoreResult(id=1, fitness_score=raw, weighted_score=0)],
            ),
        )

    engine.krkn_client.run.side_effect = evaluate
    engine.simulate()


def test_generation_saturation_ignores_generations_that_improve(
    genetic_algorithm, monkeypatch
):
    _run_with_scores(genetic_algorithm, monkeypatch, growth=10)

    assert genetic_algorithm.completed_generations == 4


def test_generation_saturation_stops_when_impact_is_flat(
    genetic_algorithm, monkeypatch
):
    _run_with_scores(genetic_algorithm, monkeypatch, growth=1)

    assert genetic_algorithm.completed_generations == 2


@pytest.mark.parametrize("growth,expected_stagnant", [(10, 0), (1, 1)])
def test_adaptive_mutation_sees_real_improvement(
    genetic_algorithm, monkeypatch, growth, expected_stagnant
):
    genetic_algorithm.algo_config.adaptive_mutation.enable = True
    genetic_algorithm.algo_config.adaptive_mutation.generations = 10
    genetic_algorithm.algo_config.adaptive_mutation.threshold = 0.1
    seen = []
    original = genetic_algorithm.adapt_mutation_rate

    def spy():
        original()
        seen.append(genetic_algorithm.stagnant_generations)

    monkeypatch.setattr(genetic_algorithm, "adapt_mutation_rate", spy)
    _run_with_scores(genetic_algorithm, monkeypatch, growth=growth)

    assert seen[-1] == expected_stagnant
