#
# Copyright 2024 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from unittest.mock import Mock, patch

from krkn_ai.algorithm.genetic import GeneticAlgorithm


class TestDurationModeOvershoot:
    """Test duration mode overshoot fixes in simulate loop"""

    def test_loop_exits_before_generation_when_budget_exhausted(
        self, minimal_config, temp_output_dir
    ):
        """Loop exits when elapsed >= duration before starting a new generation"""
        minimal_config.duration = 60

        with patch("krkn_ai.algorithm.genetic.KrknRunner") as mock_runner_class:
            mock_runner = Mock()
            mock_runner_class.return_value = mock_runner

            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]

                ga = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )

                # Mock time.monotonic to simulate elapsed > duration
                with patch("time.monotonic") as mock_monotonic:
                    # start_time, then the check inside loop
                    mock_monotonic.side_effect = [0.0, 65.0]

                    with patch("time.time", return_value=0.0):
                        with patch("time.sleep") as mock_sleep:
                            ga.simulate()

                            # Should have broken out of loop before calculating fitness (generation 1)
                            # And sleep shouldn't be called because the loop exited
                            mock_sleep.assert_not_called()
                            assert ga.completed_generations == 0

    def test_wait_sleep_skipped_when_no_budget_remains(
        self, minimal_config, temp_output_dir
    ):
        """wait_duration sleep is skipped when no time remains"""
        minimal_config.duration = 60
        minimal_config.wait_duration = 30

        with patch("krkn_ai.algorithm.genetic.KrknRunner") as mock_runner_class:
            mock_runner = Mock()
            mock_runner.run = Mock()
            mock_runner.run.return_value.fitness_result.fitness_score = 10.0
            mock_runner.run.return_value.scenario = Mock()
            mock_runner_class.return_value = mock_runner

            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]

                ga = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )
                ga.krkn_client = mock_runner
                ga.run_baseline = Mock()

                with patch("time.monotonic") as mock_monotonic:
                    # 1: start_time
                    # 2: before gen check (0 -> 10s elapsed)
                    # 3: before sleep check (10 -> 65s elapsed)
                    mock_monotonic.side_effect = [0.0, 10.0, 65.0]

                    with patch("time.time", return_value=0.0):
                        with patch("time.sleep") as mock_sleep:
                            ga.simulate()

                            # Should have completed 1 generation and exited before sleep
                            assert ga.completed_generations == 1
                            mock_sleep.assert_not_called()

    def test_wait_sleeps_only_remaining_time(self, minimal_config, temp_output_dir):
        """A generation that starts with time remaining runs to completion and sleeps remaining time"""
        minimal_config.duration = 60
        minimal_config.wait_duration = 30

        with patch("krkn_ai.algorithm.genetic.KrknRunner") as mock_runner_class:
            mock_runner = Mock()
            mock_runner.run = Mock()
            mock_runner.run.return_value.fitness_result.fitness_score = 10.0
            mock_runner.run.return_value.scenario = Mock()
            mock_runner_class.return_value = mock_runner

            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]

                ga = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )
                ga.krkn_client = mock_runner
                ga.run_baseline = Mock()

                with patch("time.monotonic") as mock_monotonic:
                    # 1: start_time (0s)
                    # 2: before gen 1 check (10s elapsed)
                    # 3: before sleep gen 1 check (45s elapsed, remaining = 15s) -> sleep(15)
                    # 4: before gen 2 check (65s elapsed, after sleep) -> exits loop
                    mock_monotonic.side_effect = [0.0, 10.0, 45.0, 65.0]

                    with patch("time.time", return_value=0.0):
                        with patch("time.sleep") as mock_sleep:
                            ga.simulate()

                            assert ga.completed_generations == 1
                            mock_sleep.assert_called_once_with(15.0)

    def test_generation_mode_unaffected(self, minimal_config, temp_output_dir):
        """Existing generations-based loop is unaffected by this change"""
        minimal_config.duration = None
        minimal_config.generations = 2
        minimal_config.wait_duration = 5

        with patch("krkn_ai.algorithm.genetic.KrknRunner") as mock_runner_class:
            mock_runner = Mock()
            mock_runner.run = Mock()
            mock_runner.run.return_value.fitness_result.fitness_score = 10.0
            mock_runner.run.return_value.scenario = Mock()
            mock_runner_class.return_value = mock_runner

            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]

                ga = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )
                ga.krkn_client = mock_runner
                ga.run_baseline = Mock()

                with patch("time.monotonic") as mock_monotonic:
                    # start_time, then unused monotonic calls since duration is None
                    mock_monotonic.side_effect = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
                    with patch("time.time", return_value=0.0):
                        with patch("time.sleep") as mock_sleep:
                            ga.simulate()

                            assert ga.completed_generations == 2
                            # Sleep called twice with wait_duration=5
                            assert mock_sleep.call_count == 2
                            mock_sleep.assert_called_with(5)
