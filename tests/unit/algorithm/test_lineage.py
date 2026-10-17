"""
Evolutionary lineage tracking tests
"""

import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from krkn_ai.algorithm.genetic.engine import GeneticAlgorithm
from krkn_ai.models.app import CommandRunResult, FitnessResult
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.scenario.base import ScenarioOrigin
from krkn_ai.models.scenario.scenario_dummy import DummyScenario


class TestTagLineage:
    """Test _tag_lineage helper"""

    def test_tag_lineage_sets_fields(self, genetic_algorithm):
        scenario = DummyScenario(cluster_components=ClusterComponents())
        original_id = scenario.id

        GeneticAlgorithm._tag_lineage(
            scenario, ["parent-a", "parent-b"], ScenarioOrigin.CROSSOVER
        )

        assert scenario.id != original_id
        assert scenario.parent_ids == ["parent-a", "parent-b"]
        assert scenario.origin == ScenarioOrigin.CROSSOVER

    def test_tag_lineage_assigns_unique_ids(self, genetic_algorithm):
        s1 = DummyScenario(cluster_components=ClusterComponents())
        s2 = DummyScenario(cluster_components=ClusterComponents())

        GeneticAlgorithm._tag_lineage(s1, [], ScenarioOrigin.COMPOSITION)
        GeneticAlgorithm._tag_lineage(s2, [], ScenarioOrigin.COMPOSITION)

        assert s1.id != s2.id

    def test_tag_lineage_copies_parent_ids(self, genetic_algorithm):
        s1 = DummyScenario(cluster_components=ClusterComponents())
        s2 = DummyScenario(cluster_components=ClusterComponents())
        shared_ids = ["parent-a", "parent-b"]

        GeneticAlgorithm._tag_lineage(s1, shared_ids, ScenarioOrigin.CROSSOVER)
        GeneticAlgorithm._tag_lineage(s2, shared_ids, ScenarioOrigin.CROSSOVER)

        assert s1.parent_ids is not s2.parent_ids
        assert s1.parent_ids == s2.parent_ids

    def test_tag_lineage_preserves_mutation_origin(self, genetic_algorithm):
        scenario = DummyScenario(cluster_components=ClusterComponents())
        scenario.origin = ScenarioOrigin.TYPE_MUTATION

        GeneticAlgorithm._tag_lineage(scenario, ["p1"], ScenarioOrigin.CROSSOVER)

        assert scenario.origin == ScenarioOrigin.TYPE_MUTATION

    def test_tag_lineage_sets_origin_when_none(self, genetic_algorithm):
        scenario = DummyScenario(cluster_components=ClusterComponents())
        assert scenario.origin is None

        GeneticAlgorithm._tag_lineage(scenario, ["p1"], ScenarioOrigin.COMPOSITION)

        assert scenario.origin == ScenarioOrigin.COMPOSITION


class TestInitialPopulationLineage:
    """Test that create_population tags scenarios with INITIAL origin"""

    def test_initial_population_has_initial_origin(self, genetic_algorithm):
        mock_scenario = DummyScenario(cluster_components=ClusterComponents())

        with patch(
            "krkn_ai.algorithm.genetic.engine.ScenarioFactory.generate_random_scenario"
        ) as mock_gen:
            mock_gen.return_value = mock_scenario
            population = genetic_algorithm.create_population(4)

        for scenario in population:
            assert scenario.origin == ScenarioOrigin.INITIAL

    def test_initial_population_has_no_parents(self, genetic_algorithm):
        mock_scenario = DummyScenario(cluster_components=ClusterComponents())

        with patch(
            "krkn_ai.algorithm.genetic.engine.ScenarioFactory.generate_random_scenario"
        ) as mock_gen:
            mock_gen.return_value = mock_scenario
            population = genetic_algorithm.create_population(4)

        for scenario in population:
            assert scenario.parent_ids == []


@pytest.mark.parametrize(
    "parent_origin",
    [
        ScenarioOrigin.INITIAL,
        ScenarioOrigin.PARAMETER_MUTATION,
        ScenarioOrigin.TYPE_MUTATION,
    ],
)
def test_unmutated_generation_preserves_fitness_and_child_lineage(
    genetic_algorithm, monkeypatch, parent_origin
):
    engine = genetic_algorithm
    engine.config.baseline.enable = False
    engine.config.fitness_function.items = []
    engine.algo_config.population_size = 2
    engine.algo_config.generations = 2
    engine.algo_config.crossover_rate = 0.0
    engine.algo_config.mutation_rate = 0.0
    engine.algo_config.composition_rate = 0.0
    engine.algo_config.population_injection_rate = 0.0
    engine.current_scenario_mutation_rate = 0.0
    parents = [
        DummyScenario(cluster_components=ClusterComponents(), origin=parent_origin)
        for _ in range(2)
    ]
    parents[0].end.value = 10
    parents[1].end.value = 20
    monkeypatch.setattr(engine, "create_population", lambda size: parents)
    monkeypatch.setattr(
        engine, "select_parents", lambda results: tuple(r.scenario for r in results)
    )

    def evaluate(scenario, generation):
        now = datetime.datetime.now(datetime.timezone.utc)
        return CommandRunResult(
            generation_id=generation,
            scenario=scenario,
            cmd="",
            log="",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=FitnessResult(fitness_score=float(scenario.end.value)),
        )

    engine.krkn_client.run.side_effect = evaluate
    engine.simulate()
    engine.save()
    summary = json.loads((Path(engine.output_dir) / "results.json").read_text())

    assert engine.krkn_client.run.call_count == 2
    assert summary["fitness_progression"] == [
        {"generation": 0, "best": 20.0, "average": 15.0},
        {"generation": 1, "best": 20.0, "average": 15.0},
    ]
    children = [row for row in summary["population_lineage"] if row["generation"] == 1]
    assert len(children) == 2
    for child in children:
        assert child["origin"] == ScenarioOrigin.CROSSOVER
        assert child["scenario_uuid"] not in [p.id for p in parents]
        assert set(child["parent_ids"]) == {p.id for p in parents}
