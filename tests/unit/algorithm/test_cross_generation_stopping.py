"""
Stopping criteria and adaptive mutation compare generations on one scale
"""

import datetime
import itertools

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
    # Keep the scenario mutation rate at 0; the default floor of 0.05 would let
    # scenario_mutation() run against the fixture's mocked scenario list.
    genetic_algorithm.algo_config.adaptive_mutation.min = 0.0
    seen = []
    original = genetic_algorithm.adapt_mutation_rate

    def spy():
        original()
        seen.append(genetic_algorithm.stagnant_generations)

    monkeypatch.setattr(genetic_algorithm, "adapt_mutation_rate", spy)
    _run_with_scores(genetic_algorithm, monkeypatch, growth=growth)

    assert seen[-1] == expected_stagnant


def test_fitness_threshold_uses_best_scenario_on_shared_scale(
    genetic_algorithm, monkeypatch
):
    """With two SLO items the per-generation ranking and the shared-scale
    ranking can disagree; the threshold must see the shared-scale best."""
    engine = genetic_algorithm
    engine.config.baseline.enable = False
    engine.config.fitness_function.items = [
        FitnessFunctionItem(id=1, query="q1"),
        FitnessFunctionItem(id=2, query="q2"),
    ]
    engine.algo_config.population_size = 4
    engine.algo_config.generations = 3
    engine.algo_config.crossover_rate = 0.0
    engine.algo_config.mutation_rate = 0.0
    engine.algo_config.composition_rate = 0.0
    engine.algo_config.population_injection_rate = 0.0
    engine.algo_config.stopping_criteria.fitness_threshold = 15.0
    engine.current_scenario_mutation_rate = 0.0

    scenarios = [
        DummyScenario(cluster_components=ClusterComponents()) for _ in range(4)
    ]
    for value, scenario in enumerate(scenarios, start=1):
        scenario.end.value = value
    pairs = itertools.cycle(
        [(scenarios[0], scenarios[1]), (scenarios[2], scenarios[3])]
    )
    monkeypatch.setattr(engine, "create_population", lambda size: scenarios)
    monkeypatch.setattr(engine, "select_parents", lambda results: next(pairs))
    monkeypatch.setattr(engine, "calculate_fitness", engine.evaluate_scenario)

    # Raw (item 1, item 2) per scenario. Generation 0 sets wide bounds and
    # nothing in it reaches the threshold. From generation 1, scenario 1 wins
    # per generation (it leads item 2 by a hair) but scenario 2 is far ahead
    # on item 1 and is the only one above the threshold on the shared scale.
    raw_scores = {
        0: {1: (1000.0, 1.0), 2: (1.0, 1000.0), 3: (1.0, 1.0), 4: (1.0, 1.0)},
        1: {1: (10.0, 31.0), 2: (1000.0, 30.0), 3: (1.0, 30.0), 4: (1.0, 30.0)},
    }

    def evaluate(scenario, generation):
        now = datetime.datetime.now(datetime.timezone.utc)
        item_1, item_2 = raw_scores[min(generation, 1)][scenario.end.value]
        return CommandRunResult(
            generation_id=generation,
            scenario=scenario,
            cmd="",
            log="",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=FitnessResult(
                scores=[
                    FitnessScoreResult(id=1, fitness_score=item_1, weighted_score=0),
                    FitnessScoreResult(id=2, fitness_score=item_2, weighted_score=0),
                ],
            ),
        )

    engine.krkn_client.run.side_effect = evaluate
    engine.simulate()

    # Stops after generation 1 instead of running to the generation limit.
    assert engine.completed_generations == 2
    assert engine.best_of_generation[1].scenario.end.value == 1
    assert engine.comparable_best_of_generation[1].scenario.end.value == 2
