import os
import unittest
from unittest.mock import MagicMock, patch


from krkn_ai.chaos_engines.krkn_runner import KrknRunner
from krkn_ai.models.config import ConfigFile, FitnessFunction, HealthCheckConfig


class TestKrknRunnerThreadLeak(unittest.TestCase):
    @patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client")
    @patch("krkn_ai.chaos_engines.krkn_runner.HealthCheckWatcher")
    @patch("krkn_ai.chaos_engines.krkn_runner.run_shell")
    def test_run_shell_exception_cleanup(
        self, mock_run_shell, mock_watcher_cls, mock_create_prom
    ):
        # Setup mocks
        mock_watcher = MagicMock()
        mock_watcher_cls.return_value = mock_watcher

        # Configure run_shell to return success by default (for init checks)
        mock_run_shell.return_value = ("output", 0)

        # Setup Config
        config = MagicMock(spec=ConfigFile)
        config.kubeconfig_file_path = "fake_path"
        config.fitness_function = MagicMock(spec=FitnessFunction)
        config.health_checks = MagicMock(spec=HealthCheckConfig)
        config.elastic = None
        config.wait_duration = 10

        from krkn_ai.models.scenario.base import Scenario

        runner = KrknRunner(config, "output_dir")

        # Create a dummy scenario
        scenario = MagicMock(spec=Scenario)
        scenario.parameters = []
        scenario.krknctl_name = "test-scenario"

        # Now make run_shell crash
        mock_run_shell.side_effect = Exception("Simulated Shell Crash")

        print("\n[TEST] Executing runner.run() with failing run_shell...")
        env = {
            "PROMETHEUS_URL": "http://localhost",
            "PROMETHEUS_TOKEN": "tok",
            "MOCK_FITNESS": "false",
            "MOCK_RUN": "false",
        }
        with patch.dict(os.environ, env):
            try:
                runner.run(scenario, 1)
            except Exception as e:
                print(f"[INFO] Caught expected exception: {e}")

        # Verification
        print("[VERIFY] Checking if HealthCheckWatcher.stop() was called...")

        # Assert that stop was called
        mock_watcher.stop.assert_called_once()
        print("[SUCCESS] stop() WAS called. Thread leak prevented.")

        # Verify run() was also called
        mock_watcher.run.assert_called()


if __name__ == "__main__":
    unittest.main()
