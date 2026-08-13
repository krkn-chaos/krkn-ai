from typing import List, Tuple

from krkn_ai.models.app import CommandRunResult
from krkn_ai.models.config import GeneticAlgorithmConfig
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class StoppingCriteriaEvaluator:
    def __init__(
        self, config: GeneticAlgorithmConfig, best_of_generation: List[CommandRunResult]
    ):
        self.config = config
        self.best_of_generation = best_of_generation
        self.saturation_stagnant_generations = 0
        self.exploration_stagnant_generations = 0
        self.new_scenarios_in_generation = 0

    def record_new_scenario(self):
        self.new_scenarios_in_generation += 1

    def evaluate(
        self, cur_generation: int, elapsed_time: float, population_size: int
    ) -> Tuple[bool, str]:
        # Hard limits first (generation count, duration), then adaptive criteria
        if (
            self.config.duration is None
            and self.config.generations is not None
            and cur_generation >= self.config.generations
        ):
            return True, f"Completed {cur_generation} generations"

        if self.config.duration is not None and elapsed_time >= self.config.duration:
            return True, f"Duration limit reached ({self.config.duration} seconds)"

        if population_size == 0:
            return True, "No more population found"

        should_stop, reason = self.check_fitness_threshold()
        if should_stop:
            return True, reason

        should_stop, reason = self.check_generation_saturation()
        if should_stop:
            return True, reason

        should_stop, reason = self.check_exploration_limit()
        if should_stop:
            return True, reason

        return False, ""

    def check_fitness_threshold(self) -> Tuple[bool, str]:
        threshold = self.config.stopping_criteria.fitness_threshold

        if threshold is None or not self.best_of_generation:
            return False, ""

        best_fitness = self.best_of_generation[-1].fitness_result.fitness_score

        if best_fitness >= threshold:
            return (
                True,
                f"Fitness threshold reached (score: {best_fitness:.4f} >= threshold: {threshold})",
            )

        return False, ""

    def check_generation_saturation(self) -> Tuple[bool, str]:
        saturation_limit = self.config.stopping_criteria.generation_saturation

        if saturation_limit is None:
            return False, ""

        if self.saturation_stagnant_generations >= saturation_limit:
            return (
                True,
                f"Generation saturation reached (no improvement for {saturation_limit} generations)",
            )

        return False, ""

    def check_exploration_limit(self) -> Tuple[bool, str]:
        exploration_limit = self.config.stopping_criteria.exploration_saturation

        if exploration_limit is None:
            return False, ""

        if self.exploration_stagnant_generations >= exploration_limit:
            return (
                True,
                f"Exploration limit reached (no new scenarios for {exploration_limit} generations)",
            )

        return False, ""

    def update_saturation_tracking(self):
        if self.config.stopping_criteria.generation_saturation is None:
            return

        if len(self.best_of_generation) < 2:
            return

        prev_best = self.best_of_generation[-2].fitness_result.fitness_score
        curr_best = self.best_of_generation[-1].fitness_result.fitness_score

        improvement = curr_best - prev_best
        threshold = self.config.stopping_criteria.saturation_threshold
        if improvement <= threshold:
            self.saturation_stagnant_generations += 1
            logger.debug(
                "No improvement in fitness score | stagnant_generations=%d/%s",
                self.saturation_stagnant_generations,
                self.config.stopping_criteria.generation_saturation,
            )
        else:
            self.saturation_stagnant_generations = 0
            logger.debug(
                "Fitness improved by %.4f, resetting saturation counter", improvement
            )

    def update_exploration_tracking(self):
        if self.config.stopping_criteria.exploration_saturation is None:
            return

        if self.new_scenarios_in_generation == 0:
            self.exploration_stagnant_generations += 1
            logger.debug(
                "No new scenarios discovered | stagnant_generations=%d/%s",
                self.exploration_stagnant_generations,
                self.config.stopping_criteria.exploration_saturation,
            )
        else:
            self.exploration_stagnant_generations = 0
            logger.debug(
                "Discovered %d new scenarios, resetting exploration counter",
                self.new_scenarios_in_generation,
            )

        self.new_scenarios_in_generation = 0
