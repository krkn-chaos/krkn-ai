"""
Population creation tests
"""

import pytest
from unittest.mock import Mock, patch

from krkn_ai.models.scenario.base import BaseScenario
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.custom_errors import UniqueScenariosError
from krkn_ai.models.cluster_components import ClusterComponents


class TestPopulationCreation:
    """Test population creation functionality"""

    def test_create_population_with_valid_size(self, genetic_algorithm):
        """Test creating population of specified size"""
        population_size = 4
        mock_scenario = DummyScenario(cluster_components=ClusterComponents())

        with patch(
            "krkn_ai.algorithm.genetic.engine.ScenarioFactory.generate_random_scenario"
        ) as mock_gen_scenario:
            mock_gen_scenario.return_value = mock_scenario
            population = genetic_algorithm.create_population(population_size)

            assert len(population) == population_size
            assert all(isinstance(s, BaseScenario) for s in population)

    def test_create_population_handles_insufficient_unique_scenarios(
        self, genetic_algorithm
    ):
        """Test population creation handles insufficient unique scenarios by duplicating"""
        population_size = 10
        # Create a scenario that will be used for duplication
        mock_scenario = DummyScenario(cluster_components=ClusterComponents())

        # Simulate limited unique scenarios: only generate 3 unique scenarios, then return None
        call_count = [0]

        def limited_scenario_generator(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 3:
                return mock_scenario
            return None

        with patch(
            "krkn_ai.algorithm.genetic.engine.ScenarioFactory.generate_random_scenario"
        ) as mock_gen_scenario:
            mock_gen_scenario.side_effect = limited_scenario_generator
            # Pre-populate seen_population with a scenario for duplication
            genetic_algorithm.seen_population = {mock_scenario: Mock()}

            population = genetic_algorithm.create_population(population_size)
            # Should duplicate existing scenarios to fill population to the required size
            assert len(population) == population_size

    def test_create_population_raises_error_when_no_available_scenarios(
        self, genetic_algorithm
    ):
        """Test population creation raises error when no scenarios available"""
        population_size = 10

        with patch(
            "krkn_ai.algorithm.genetic.engine.ScenarioFactory.generate_random_scenario"
        ) as mock_gen_scenario:
            mock_gen_scenario.return_value = None
            genetic_algorithm.seen_population = {}

            with pytest.raises(
                UniqueScenariosError, match="Please adjust population size"
            ):
                genetic_algorithm.create_population(population_size)
