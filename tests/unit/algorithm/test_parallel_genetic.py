import time
import unittest
from unittest.mock import MagicMock, patch
from krkn_ai.algorithm.genetic import GeneticAlgorithm
from krkn_ai.models.config import ConfigFile, FitnessFunction, ClusterComponents, ScenarioConfig
from krkn_ai.models.app import CommandRunResult, FitnessResult

class TestParallelGenetic(unittest.TestCase):
    def setUp(self):
        self.config_dict = {
            "kubeconfig_file_path": "/tmp/kube",
            "population_size": 4,
            "generations": 1,
            "parallel": True,
            "parallel_limit": 4,
            "fitness_function": {
                "query": "up",
                "items": []
            },
            "cluster_components": {
                "namespaces": [],
                "nodes": []
            },
            "scenario": {}
        }
        self.config = ConfigFile(**self.config_dict)

    @patch("krkn_ai.algorithm.genetic.GeneticAlgorithm.save_scenario_result")
    @patch("krkn_ai.reporter.health_check_reporter.HealthCheckReporter.plot_report")
    @patch("krkn_ai.reporter.health_check_reporter.HealthCheckReporter.write_fitness_result")
    @patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client")
    @patch("krkn_ai.algorithm.genetic.KrknRunner")
    @patch("krkn_ai.models.scenario.factory.ScenarioFactory.generate_valid_scenarios")
    @patch("krkn_ai.models.scenario.factory.ScenarioFactory.generate_random_scenario")
    @patch("krkn_ai.algorithm.genetic.GeneticAlgorithm.run_baseline")
    @patch("krkn_ai.algorithm.genetic.GeneticAlgorithm.save_config")
    def test_parallel_execution_speedup(self, mock_save_config, mock_baseline, mock_random, mock_valid, mock_runner_cls, mock_prom, mock_write, mock_plot, mock_save_res):
        # Setup mocks
        mock_runner = mock_runner_cls.return_value
        
        def slow_run(scenario, gen_id):
            time.sleep(0.5) # Simulate a slow experiment
            result = MagicMock(spec=CommandRunResult)
            result.fitness_result = FitnessResult(fitness_score=1.0)
            result.scenario = scenario
            result.scenario_id = "test"
            result.generation_id = gen_id
            result.health_check_results = {}
            result.model_dump.return_value = {}
            result.start_time = MagicMock()
            result.end_time = MagicMock()
            return result
            
        mock_runner.run.side_effect = slow_run
        
        # Mock scenario generation
        mock_scenarios = [MagicMock() for _ in range(4)]
        mock_random.side_effect = mock_scenarios
        mock_valid.return_value = []

        ga = GeneticAlgorithm(self.config, "/tmp/out", "yaml")
        
        start_time = time.time()
        # Mock simulate to only run one generation loop manually or just call it
        # Actually simulate() has a while True loop, let's mock _check_and_stop to return True after 1 gen
        with patch.object(GeneticAlgorithm, "_check_and_stop", side_effect=[False, True]):
            ga.simulate()
        
        duration = time.time() - start_time
        
        # If sequential, it would take at least 4 * 0.5 = 2.0 seconds
        # If parallel, it should take ~0.5 - 0.7 seconds
        print(f"Parallel duration: {duration}")
        assert duration < 1.5 
        assert mock_runner.run.call_count == 4

if __name__ == "__main__":
    unittest.main()
