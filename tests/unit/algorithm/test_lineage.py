"""
Evolutionary lineage tracking tests
"""

from unittest.mock import patch

from krkn_ai.algorithm.genetic.engine import GeneticAlgorithm
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
