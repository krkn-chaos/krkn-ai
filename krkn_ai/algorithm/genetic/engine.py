import copy
import datetime
import json
import os
import time
from typing import List, Optional

from krkn_ai.algorithm.base import BaseEngine
from krkn_ai.algorithm.genetic.stopping import StoppingCriteriaEvaluator
from krkn_ai.constants import STATUS_IN_PROGRESS
from krkn_ai.models.app import CommandRunResult, KrknRunnerType
from krkn_ai.models.config import ConfigFile, GeneticAlgorithmConfig, SelectionStrategy
from krkn_ai.models.custom_errors import PopulationSizeError, UniqueScenariosError
from krkn_ai.models.scenario.base import (
    Scenario,
    BaseScenario,
    CompositeDependency,
    CompositeScenario,
)
from krkn_ai.models.scenario.factory import ScenarioFactory
from krkn_ai.reporter.generations_reporter import GenerationsReporter
from krkn_ai.reporter.json_summary_reporter import JSONSummaryReporter
from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.output import format_duration
from krkn_ai.utils.rng import rng

logger = get_logger(__name__)


class GeneticAlgorithm(BaseEngine):
    def __init__(
        self,
        config: ConfigFile,
        output_dir: str,
        format: str,
        runner_type: KrknRunnerType = None,
        run_uuid: Optional[str] = None,
    ):
        if config.genetic.population_size < 2:
            raise PopulationSizeError("Population size should be at least 2")

        if config.genetic.population_size % 2 != 0:
            logger.debug(
                "Population size is odd, making it even for the genetic algorithm."
            )
            config.genetic.population_size += 1

        super().__init__(config, output_dir, format, runner_type, run_uuid)

        # Shorthand for GA-specific params; shared fields stay on self.config
        self.algo_config: GeneticAlgorithmConfig = config.genetic
        self.population: List[BaseScenario] = []
        self.best_of_generation: List[CommandRunResult] = []
        self.completed_generations: int = 0
        self.stagnant_generations = 0
        self.current_scenario_mutation_rate: float = (
            self.algo_config.scenario_mutation_rate
        )

        self.generations_reporter = GenerationsReporter(self.output_dir, self.format)
        self.stopping = StoppingCriteriaEvaluator(
            self.algo_config, self.best_of_generation
        )

    def optimize(self):
        return self.simulate()

    def simulate(self):
        try:
            results_path = os.path.join(self.output_dir, "results.json")
            if os.path.exists(results_path):
                with open(results_path, "r") as f:
                    data = json.load(f)
                data["status"] = STATUS_IN_PROGRESS
                with open(results_path, "w") as f:
                    json.dump(data, f)
        except Exception as e:
            logger.warning("Failed to update status to in progress: %s", e)

        self.start_time = datetime.datetime.now(datetime.timezone.utc)
        start_time = time.time()
        cur_generation = 0

        # Baseline run establishes cluster health before chaos testing
        self.run_baseline()

        # Initial population (Gen 0)
        self.population = self.create_population(self.algo_config.population_size)

        while True:
            elapsed_time = time.time() - start_time

            # Check stopping criteria before evaluating next generation
            if self._check_and_stop(cur_generation, elapsed_time):
                break

            if self.algo_config.duration is not None:
                remaining_time = self.algo_config.duration - elapsed_time
                logger.debug(
                    "Elapsed time: %s, Remaining: %s",
                    format_duration(elapsed_time),
                    format_duration(remaining_time),
                )

            logger.info("| Population |")
            logger.info("--------------------------------------------------------")
            for scenario in self.population:
                logger.info("%s, ", scenario)
            logger.info("--------------------------------------------------------")

            logger.info("| Generation %d |", cur_generation + 1)
            logger.info("--------------------------------------------------------")

            fitness_scores = [
                self.calculate_fitness(member, cur_generation)
                for member in self.population
            ]
            fitness_scores = sorted(
                fitness_scores,
                key=lambda x: x.fitness_result.fitness_score,
                reverse=True,
            )
            self.best_of_generation.append(fitness_scores[0])
            logger.info(
                "Best Fitness: %f", fitness_scores[0].fitness_result.fitness_score
            )

            self.adapt_mutation_rate()

            self.stopping.update_saturation_tracking()
            self.stopping.update_exploration_tracking()

            cur_generation += 1

            elapsed_after_eval = time.time() - start_time
            if self._check_and_stop(cur_generation, elapsed_after_eval):
                break

            # Repopulate: each pair of parents produces 2 offspring
            self.population = []
            for _ in range(self.algo_config.population_size // 2):
                parent1, parent2 = self.select_parents(fitness_scores)
                child1, child2 = None, None
                if rng.random() < self.algo_config.composition_rate:
                    # Composition: merge two scenarios into a composite
                    child1 = self.composition(
                        copy.deepcopy(parent1), copy.deepcopy(parent2)
                    )
                    child1 = self.mutate(child1)
                    self.population.append(child1)

                    child2 = self.composition(
                        copy.deepcopy(parent2), copy.deepcopy(parent1)
                    )
                    child2 = self.mutate(child2)
                    self.population.append(child2)
                else:
                    # Standard crossover: swap parameters between parents
                    child1, child2 = self.crossover(
                        copy.deepcopy(parent1), copy.deepcopy(parent2)
                    )
                    child1 = self.mutate(child1)
                    child2 = self.mutate(child2)

                    self.population.append(child1)
                    self.population.append(child2)

            # Inject random members to diversify the gene pool
            if rng.random() < self.algo_config.population_injection_rate:
                self.population.extend(
                    self.create_population(self.algo_config.population_injection_size)
                )

    def _check_and_stop(self, cur_generation: int, elapsed_time: float) -> bool:
        should_stop, reason = self.stopping.evaluate(
            cur_generation, elapsed_time, len(self.population)
        )
        if should_stop:
            self.end_time = datetime.datetime.now(datetime.timezone.utc)
            logger.info("Stopping algorithm: %s", reason)
            logger.info(
                "Completed %d generations in %s",
                cur_generation,
                format_duration(elapsed_time),
            )
            self.completed_generations = cur_generation
            self.end_time = datetime.datetime.now(datetime.timezone.utc)
            return True
        return False

    def save(self):
        self.generations_reporter.save_best_generations(self.best_of_generation)
        self.generations_reporter.save_best_generation_graph(self.best_of_generation)
        self.health_check_reporter.save_report(self.seen_population.values())
        self.health_check_reporter.sort_fitness_result_csv()

        summary_reporter = JSONSummaryReporter(
            run_uuid=self.run_uuid,
            config=self.config,
            algo_config=self.algo_config,
            seen_population=self.seen_population,
            best_of_generation=self.best_of_generation,
            baseline_result=self.baseline_result,
            start_time=self.start_time,
            end_time=self.end_time,
            completed_generations=self.completed_generations,
            seed=self.seed,
            scenario_mutation_rate=self.current_scenario_mutation_rate,
        )
        summary_reporter.save(self.output_dir)

        if self.elastic_client is not None:
            self.elastic_client.index_run_summary(
                summary_reporter.generate_summary(), self.run_uuid
            )

    def adapt_mutation_rate(self):
        cfg = self.algo_config.adaptive_mutation

        if not cfg.enable:
            return

        if len(self.best_of_generation) < 2:
            return

        prev = self.best_of_generation[-2].fitness_result.fitness_score
        curr = self.best_of_generation[-1].fitness_result.fitness_score

        improvement = curr - prev

        if improvement < cfg.threshold:
            self.stagnant_generations += 1
            if self.stagnant_generations < cfg.generations:
                return
            rate_factor = 1.2
        else:
            self.stagnant_generations = 0
            rate_factor = 0.9

        if cfg.min > cfg.max:
            raise ValueError(
                f"Invalid adaptive mutation configuration: min ({cfg.min}) "
                f"must be less than or equal to max ({cfg.max})"
            )

        # Increase rate when stagnating, decrease when improving
        old_rate = self.current_scenario_mutation_rate
        self.current_scenario_mutation_rate *= rate_factor

        # Clamp to configured bounds
        self.current_scenario_mutation_rate = max(
            cfg.min, min(self.current_scenario_mutation_rate, cfg.max)
        )

        if self.current_scenario_mutation_rate != old_rate:
            logger.info(
                "Adaptive mutation triggered | scenario_mutation_rate=%.4f",
                self.current_scenario_mutation_rate,
            )

        self.stagnant_generations = 0

    def create_population(self, population_size) -> List[BaseScenario]:
        logger.info("Creating population of size %d", population_size)

        already_seen = set()
        attempts = 0
        max_attempts = population_size * 10

        population: List[BaseScenario] = []
        while len(population) < population_size and attempts < max_attempts:
            attempts += 1
            scenario = ScenarioFactory.generate_random_scenario(
                self.config, self.valid_scenarios
            )

            if scenario and scenario not in already_seen:
                population.append(scenario)
                already_seen.add(scenario)

        if len(population) < population_size:
            missing = population_size - len(population)
            logger.warning(
                "Could not generate enough unique scenarios, duplicating %d samples",
                missing,
            )

            available_scenarios = list(
                set(population.copy()) | set(self.seen_population.keys())
            )

            if len(available_scenarios) == 0:
                raise UniqueScenariosError(
                    "Please adjust population size or scenario configuration to generate unique scenarios."
                )

            for _ in range(missing):
                population.append(rng.choice(available_scenarios))

        return population

    def calculate_fitness(self, scenario: BaseScenario, generation_id: int):
        if scenario in self.seen_population:
            logger.info(
                "Scenario %s already evaluated, skipping fitness calculation.",
                scenario,
            )
            result = self.seen_population[scenario]
            result = copy.deepcopy(result)
            result.generation_id = generation_id
            return result

        self.stopping.record_new_scenario()

        scenario_result = self.evaluate_scenario(scenario, generation_id)
        return scenario_result

    def mutate(self, scenario: BaseScenario):
        if isinstance(scenario, CompositeScenario):
            scenario.scenario_a = self.mutate(scenario.scenario_a)
            scenario.scenario_b = self.mutate(scenario.scenario_b)
            return scenario

        if rng.random() < self.current_scenario_mutation_rate:
            success, new_scenario = self.scenario_mutation(scenario)
            if success:
                return new_scenario

        if hasattr(scenario, "mutate"):
            scenario.mutate()
        else:
            logger.warning("Scenario %s does not have mutate method", scenario)
        return scenario

    def scenario_mutation(self, scenario: BaseScenario):
        common_scenarios = []
        for _, scenario_cls in self.valid_scenarios:
            new_scenario = scenario_cls(
                cluster_components=self.config.cluster_components.get_active_components()
            )

            common_params = set([type(x) for x in new_scenario.parameters]) & set(
                [type(x) for x in scenario.parameters]
            )
            if len(common_params) > 0 and not isinstance(new_scenario, type(scenario)):
                common_scenarios.append(new_scenario)

        if len(common_scenarios) == 0:
            logger.debug("No common scenarios found, returning original scenario")
            return False, scenario

        new_scenario = rng.choice(common_scenarios)

        common_params = set([type(x) for x in new_scenario.parameters]) & set(
            [type(x) for x in scenario.parameters]
        )
        for param_type in common_params:
            param_value = self.__get_param_value(scenario, param_type)
            self.__set_param_value(new_scenario, param_type, param_value)

        return True, new_scenario

    def select_parents(self, fitness_scores: List[CommandRunResult]):
        if self.algo_config.selection_strategy == SelectionStrategy.tournament:
            parent1 = self.tournament_selection(
                fitness_scores, self.algo_config.tournament_size
            )
            parent2 = self.tournament_selection(
                fitness_scores, self.algo_config.tournament_size
            )
            return parent1, parent2

        return self.roulette_wheel_selection(fitness_scores)

    def tournament_selection(
        self, fitness_scores: List[CommandRunResult], tournament_size: int
    ):
        population_size = len(fitness_scores)
        size = min(tournament_size, population_size)

        weights = [1.0 / population_size] * population_size
        participants = rng.choices(items=fitness_scores, weights=weights, k=size)

        best = max(participants, key=lambda x: x.fitness_result.fitness_score)
        return best.scenario

    def roulette_wheel_selection(self, fitness_scores: List[CommandRunResult]):
        raw = [x.fitness_result.fitness_score for x in fitness_scores]
        scenarios = [x.scenario for x in fitness_scores]

        min_f = min(raw)
        max_f = max(raw)

        if max_f == min_f:
            shifted: List[float] = [1.0 for _ in raw]
        else:
            shifted = [(f - min_f) / (max_f - min_f) + 1e-8 for f in raw]

        total_fitness = sum(shifted)

        if total_fitness == 0:
            return rng.choice(scenarios), rng.choice(scenarios)

        probabilities = [f / total_fitness for f in shifted]

        parent1 = rng.choices(items=scenarios, weights=probabilities, k=1)[0]
        parent2 = rng.choices(items=scenarios, weights=probabilities, k=1)[0]
        return parent1, parent2

    def crossover(self, scenario_a: BaseScenario, scenario_b: BaseScenario):
        if isinstance(scenario_a, CompositeScenario) and isinstance(
            scenario_b, CompositeScenario
        ):
            scenario_a.scenario_b, scenario_b.scenario_b = (
                scenario_b.scenario_b,
                scenario_a.scenario_b,
            )
            return scenario_a, scenario_b
        elif isinstance(scenario_a, CompositeScenario) or isinstance(
            scenario_b, CompositeScenario
        ):
            if isinstance(scenario_a, CompositeScenario):
                a_b = scenario_a.scenario_b
                scenario_a.scenario_b = scenario_b
                return scenario_a, a_b
            else:
                b_a = scenario_b.scenario_a
                scenario_b.scenario_a = scenario_a
                return b_a, scenario_b

        if not hasattr(scenario_a, "parameters") or not hasattr(
            scenario_b, "parameters"
        ):
            logger.warning(
                "Scenario %s or %s does not have property 'parameters'",
                scenario_a,
                scenario_b,
            )
            return scenario_a, scenario_b

        common_params = set([type(x) for x in scenario_a.parameters]) & set(
            [type(x) for x in scenario_b.parameters]
        )

        if len(common_params) == 0:
            return scenario_a, scenario_b
        else:
            for param_type in common_params:
                if rng.random() < self.algo_config.crossover_rate:
                    a_value = self.__get_param_value(scenario_a, param_type)
                    b_value = self.__get_param_value(scenario_b, param_type)

                    self.__set_param_value(scenario_a, param_type, b_value)
                    self.__set_param_value(scenario_b, param_type, a_value)

            return scenario_a, scenario_b

    def composition(self, scenario_a: BaseScenario, scenario_b: BaseScenario):
        dependency = rng.choice(
            [
                CompositeDependency.NONE,
                CompositeDependency.A_ON_B,
                CompositeDependency.B_ON_A,
            ]
        )
        composite_scenario = CompositeScenario(
            name="composite",
            scenario_a=scenario_a,
            scenario_b=scenario_b,
            dependency=dependency,
        )
        return composite_scenario

    def __get_param_value(self, scenario: Scenario, param_type):
        for param in scenario.parameters:
            if isinstance(param, param_type):
                return param.value
        raise ValueError(
            f"Parameter type {param_type} not found in scenario {scenario}"
        )

    def __set_param_value(self, scenario: Scenario, param_type, value):
        for param in scenario.parameters:
            if isinstance(param, param_type):
                param.value = value
                return
