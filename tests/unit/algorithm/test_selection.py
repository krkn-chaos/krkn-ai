"""
Parent selection algorithm tests
"""

import datetime

from krkn_ai.models.app import CommandRunResult, FitnessResult
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.cluster_components import ClusterComponents


class TestSelection:
    """Test parent selection functionality"""

    def test_select_parents_with_different_fitness(self, genetic_algorithm):
        """Test parent selection with different fitness scores using roulette wheel selection"""
        scenario1 = DummyScenario(cluster_components=ClusterComponents())
        scenario2 = DummyScenario(cluster_components=ClusterComponents())
        scenario3 = DummyScenario(cluster_components=ClusterComponents())

        fitness_scores = [
            CommandRunResult(
                generation_id=0,
                scenario=scenario1,
                fitness_result=FitnessResult(fitness_score=10.0),
                cmd="",
                log="",
                returncode=0,
                start_time=datetime.datetime.now(),
                end_time=datetime.datetime.now(),
            ),
            CommandRunResult(
                generation_id=0,
                scenario=scenario2,
                fitness_result=FitnessResult(fitness_score=20.0),
                cmd="",
                log="",
                returncode=0,
                start_time=datetime.datetime.now(),
                end_time=datetime.datetime.now(),
            ),
            CommandRunResult(
                generation_id=0,
                scenario=scenario3,
                fitness_result=FitnessResult(fitness_score=30.0),
                cmd="",
                log="",
                returncode=0,
                start_time=datetime.datetime.now(),
                end_time=datetime.datetime.now(),
            ),
        ]

        parent1, parent2 = genetic_algorithm.select_parents(fitness_scores)

        # Should return two parents from the input scenarios
        expected_scenarios = [scenario1, scenario2, scenario3]
        assert parent1 in expected_scenarios
        assert parent2 in expected_scenarios
        # Both parents should be valid scenarios (may be same or different)
        assert parent1 is not None
        assert parent2 is not None

    def test_select_parents_with_identical_fitness(self, genetic_algorithm):
        """Test parent selection when all fitness scores are identical (equal probability)"""
        scenario1 = DummyScenario(cluster_components=ClusterComponents())
        scenario2 = DummyScenario(cluster_components=ClusterComponents())

        fitness_scores = [
            CommandRunResult(
                generation_id=0,
                scenario=scenario1,
                fitness_result=FitnessResult(fitness_score=10.0),
                cmd="",
                log="",
                returncode=0,
                start_time=datetime.datetime.now(),
                end_time=datetime.datetime.now(),
            ),
            CommandRunResult(
                generation_id=0,
                scenario=scenario2,
                fitness_result=FitnessResult(fitness_score=10.0),
                cmd="",
                log="",
                returncode=0,
                start_time=datetime.datetime.now(),
                end_time=datetime.datetime.now(),
            ),
        ]

        parent1, parent2 = genetic_algorithm.select_parents(fitness_scores)

        # Should return two parents (equal probability when fitness is identical)
        expected_scenarios = [scenario1, scenario2]
        assert parent1 in expected_scenarios
        assert parent2 in expected_scenarios
        assert parent1 is not None
        assert parent2 is not None

    def test_select_parents_tournament(self, genetic_algorithm):
        """Test tournament selection picks the best from a small pool"""
        from krkn_ai.models.config import SelectionStrategy

        scenario1 = DummyScenario(cluster_components=ClusterComponents())
        scenario2 = DummyScenario(cluster_components=ClusterComponents())
        scenario3 = DummyScenario(cluster_components=ClusterComponents())

        fitness_scores = [
            CommandRunResult(
                generation_id=0,
                scenario=scenario1,
                fitness_result=FitnessResult(fitness_score=10.0),
                cmd="",
                log="",
                returncode=0,
                start_time=datetime.datetime.now(),
                end_time=datetime.datetime.now(),
            ),
            CommandRunResult(
                generation_id=0,
                scenario=scenario2,
                fitness_result=FitnessResult(fitness_score=50.0),
                cmd="",
                log="",
                returncode=0,
                start_time=datetime.datetime.now(),
                end_time=datetime.datetime.now(),
            ),
            CommandRunResult(
                generation_id=0,
                scenario=scenario3,
                fitness_result=FitnessResult(fitness_score=100.0),
                cmd="",
                log="",
                returncode=0,
                start_time=datetime.datetime.now(),
                end_time=datetime.datetime.now(),
            ),
        ]

        # Configure for tournament selection
        genetic_algorithm.algo_config.selection_strategy = SelectionStrategy.tournament
        genetic_algorithm.algo_config.tournament_size = 2

        parent1, parent2 = genetic_algorithm.select_parents(fitness_scores)

        # Parents should be among the top 2 if tournament size is 2 (mostly)
        # but definitely valid scenarios
        expected_scenarios = [scenario1, scenario2, scenario3]
        assert parent1 in expected_scenarios
        assert parent2 in expected_scenarios
