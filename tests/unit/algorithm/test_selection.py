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
        genetic_algorithm.config.selection_strategy = SelectionStrategy.tournament
        genetic_algorithm.config.tournament_size = 2

        parent1, parent2 = genetic_algorithm.select_parents(fitness_scores)

        # Parents should be among the top 2 if tournament size is 2 (mostly)
        # but definitely valid scenarios
        expected_scenarios = [scenario1, scenario2, scenario3]
        assert parent1 in expected_scenarios
        assert parent2 in expected_scenarios

    def test_tournament_selection_size_exceeds_population(self, genetic_algorithm):
        """Test tournament selection when tournament_size > population size (clamped)"""
        from krkn_ai.models.config import SelectionStrategy

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
                fitness_result=FitnessResult(fitness_score=90.0),
                cmd="",
                log="",
                returncode=0,
                start_time=datetime.datetime.now(),
                end_time=datetime.datetime.now(),
            ),
        ]

        # tournament_size (10) > population (2): should clamp without error
        genetic_algorithm.config.selection_strategy = SelectionStrategy.tournament
        genetic_algorithm.config.tournament_size = 10

        parent1, parent2 = genetic_algorithm.select_parents(fitness_scores)

        expected_scenarios = [scenario1, scenario2]
        assert parent1 in expected_scenarios
        assert parent2 in expected_scenarios

    def test_tournament_selection_equal_fitness(self, genetic_algorithm):
        """Test tournament selection when all individuals have equal fitness"""
        from krkn_ai.models.config import SelectionStrategy

        scenario1 = DummyScenario(cluster_components=ClusterComponents())
        scenario2 = DummyScenario(cluster_components=ClusterComponents())
        scenario3 = DummyScenario(cluster_components=ClusterComponents())

        fitness_scores = [
            CommandRunResult(
                generation_id=0,
                scenario=scenario1,
                fitness_result=FitnessResult(fitness_score=50.0),
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
                fitness_result=FitnessResult(fitness_score=50.0),
                cmd="",
                log="",
                returncode=0,
                start_time=datetime.datetime.now(),
                end_time=datetime.datetime.now(),
            ),
        ]

        genetic_algorithm.config.selection_strategy = SelectionStrategy.tournament
        genetic_algorithm.config.tournament_size = 2

        parent1, parent2 = genetic_algorithm.select_parents(fitness_scores)

        # All have equal fitness, any selection is valid
        expected_scenarios = [scenario1, scenario2, scenario3]
        assert parent1 in expected_scenarios
        assert parent2 in expected_scenarios


class TestSelectionConfig:
    """Test selection strategy configuration validation"""

    def test_tournament_size_below_minimum_raises(self):
        """tournament_size < 2 should raise ValidationError"""
        import pytest
        from krkn_ai.models.config import ConfigFile

        with pytest.raises(Exception, match="tournament_size must be at least 2"):
            ConfigFile(
                kubeconfig_file_path="/tmp/kube",
                tournament_size=1,
                fitness_function={"query": "up"},
                cluster_components={},
            )

    def test_tournament_size_minimum_accepted(self):
        """tournament_size = 2 should be accepted"""
        from krkn_ai.models.config import ConfigFile

        config = ConfigFile(
            kubeconfig_file_path="/tmp/kube",
            tournament_size=2,
            fitness_function={"query": "up"},
            cluster_components={},
        )
        assert config.tournament_size == 2

    def test_default_selection_strategy_is_roulette(self):
        """Default selection strategy should be roulette"""
        from krkn_ai.models.config import ConfigFile, SelectionStrategy

        config = ConfigFile(
            kubeconfig_file_path="/tmp/kube",
            fitness_function={"query": "up"},
            cluster_components={},
        )
        assert config.selection_strategy == SelectionStrategy.roulette
        assert config.tournament_size == 3
