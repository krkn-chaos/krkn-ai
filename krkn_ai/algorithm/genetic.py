import os
import copy
import json
import time
import uuid
from typing_extensions import Dict
import yaml
from typing import List, Optional

from krkn_ai.models.app import CommandRunResult, KrknRunnerType

from krkn_ai.models.scenario.base import (
    Scenario,
    BaseScenario,
    CompositeDependency,
    CompositeScenario,
)
from krkn_ai.models.scenario.factory import ScenarioFactory

from krkn_ai.models.config import ConfigFile
from krkn_ai.reporter.generations_reporter import GenerationsReporter
from krkn_ai.reporter.health_check_reporter import HealthCheckReporter
from krkn_ai.utils.logger import get_logger
from krkn_ai.chaos_engines.krkn_runner import KrknRunner
from krkn_ai.utils.rng import rng
from krkn_ai.models.custom_errors import PopulationSizeError, UniqueScenariosError
from krkn_ai.utils.output import format_result_filename, format_duration
from krkn_ai.utils.elastic_client import ElasticSearchClient

logger = get_logger(__name__)


class GeneticAlgorithm:
    """
    A class implementing a Genetic Algorithm for scenario optimization.
    """

    def __init__(
        self,
        config: ConfigFile,
        output_dir: str,
        format: str,
        runner_type: KrknRunnerType = None,
    ):
        self.krkn_client = KrknRunner(
            config, output_dir=output_dir, runner_type=runner_type
        )
        self.output_dir = output_dir
        self.config = config
        self.population: List[BaseScenario] = []
        self.format = format

        self.stagnant_generations = 0

        self.valid_scenarios = ScenarioFactory.generate_valid_scenarios(
            self.config
        )  # List valid scenarios
        self.seen_population: Dict[
            BaseScenario, CommandRunResult
        ] = {}  # Map between scenario and its result
        self.best_of_generation: List[BaseScenario] = []

        self.health_check_reporter = HealthCheckReporter(
            self.output_dir, self.config.output
        )
        self.generations_reporter = GenerationsReporter(self.output_dir, self.format)
        # Only initialize ElasticSearchClient if elastic config is provided
        self.elastic_client: Optional[ElasticSearchClient] = None
        if self.config.elastic is not None:
            self.elastic_client = ElasticSearchClient(self.config.elastic)

        # Generate unique run UUID for this experiment
        self.run_uuid = str(uuid.uuid4())
        logger.info("Krkn-AI run UUID: %s", self.run_uuid)

        if self.config.population_size < 2:
            raise PopulationSizeError("Population size should be at least 2")

        # Population size should be even
        if self.config.population_size % 2 != 0:
            logger.debug(
                "Population size is odd, making it even for the genetic algorithm."
            )
            self.config.population_size += 1

        self.save_config()
        if self.elastic_client is not None:
            self.elastic_client.index_config(self.config, self.run_uuid)

        # For debugging configuration
        # logger.debug("CONFIG")
        # logger.debug("--------------------------------------------------------")
        # logger.debug("%s", json.dumps(self.config.model_dump(), indent=2))

    def simulate(self):
        # Initial population (Gen 0)
        self.population = self.create_population(self.config.population_size)

        # Variables to track the progress of the algorithm
        start_time = time.time()
        cur_generation = 0

        while True:
            # Calculate elapsed time since the start of the algorithm
            elapsed_time = time.time() - start_time

            # Check generation limit if duration is not set
            if (
                self.config.duration is None
                and cur_generation >= self.config.generations
            ):
                logger.info(
                    "Completed %d generations in %s",
                    cur_generation,
                    format_duration(elapsed_time),
                )
                break

            # Check if duration has been exceeded
            if self.config.duration is not None:
                if elapsed_time >= self.config.duration:
                    logger.info(
                        "Duration limit reached (%d seconds). Stopping algorithm.",
                        self.config.duration,
                    )
                    logger.info(
                        "Completed %d generations in %s",
                        cur_generation,
                        format_duration(elapsed_time),
                    )
                    break
                remaining_time = self.config.duration - elapsed_time
                logger.debug(
                    "Elapsed time: %s, Remaining: %s",
                    format_duration(elapsed_time),
                    format_duration(remaining_time),
                )

            if len(self.population) == 0:
                logger.warning("No more population found, stopping generations.")
                break

            logger.info("| Population |")
            logger.info("--------------------------------------------------------")
            for scenario in self.population:
                logger.info("%s, ", scenario)
            logger.info("--------------------------------------------------------")

            logger.info("| Generation %d |", cur_generation + 1)
            logger.info("--------------------------------------------------------")

            # Evaluate fitness of the current population
            fitness_scores = [
                self.calculate_fitness(member, cur_generation)
                for member in self.population
            ]
            # Find the best individual in the current generation
            # Note: If there is no best solution, it will still consider based on sorting order
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

            # Repopulate off-springs
            self.population = []
            for _ in range(self.config.population_size // 2):
                parent1, parent2 = self.select_parents(fitness_scores)
                child1, child2 = None, None
                if rng.random() < self.config.composition_rate:
                    # componention crossover to generate 1 scenario
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
                    # Crossover of 2 parents to generate 2 offsprings
                    child1, child2 = self.crossover(
                        copy.deepcopy(parent1), copy.deepcopy(parent2)
                    )
                    child1 = self.mutate(child1)
                    child2 = self.mutate(child2)

                    self.population.append(child1)
                    self.population.append(child2)

            # Inject random members to population to diversify scenarios
            if rng.random() < self.config.population_injection_rate:
                self.population.extend(
                    self.create_population(self.config.population_injection_size)
                )

            cur_generation += 1

    def adapt_mutation_rate(self):
        cfg = self.config.adaptive_mutation

        if not cfg.enable:
            return

        if len(self.best_of_generation) < 2:
            return

        prev = self.best_of_generation[-2].fitness_result.fitness_score
        curr = self.best_of_generation[-1].fitness_result.fitness_score

        improvement = curr - prev

        if improvement < cfg.threshold:
            self.stagnant_generations += 1
        else:
            self.stagnant_generations = 0

        if self.stagnant_generations < cfg.generations:
            return

        # adaptive update
        if improvement < cfg.threshold:
            self.config.scenario_mutation_rate *= 1.2
        else:
            self.config.scenario_mutation_rate *= 0.9

        self.config.scenario_mutation_rate = max(
            cfg.min, min(self.config.scenario_mutation_rate, cfg.max)
        )

        logger.info(
            "Adaptive mutation triggered | mutation_rate=%.4f",
            self.config.scenario_mutation_rate,
        )

        self.stagnant_generations = 0

    def create_population(self, population_size) -> List[BaseScenario]:
        """Generate random population for algorithm"""
        logger.info("Creating population of size %d", population_size)

        already_seen = set()
        attempts = 0
        max_attempts = population_size * 10

        population: List[BaseScenario] = []
        # Make attempts to create population of given size, if not possible it will return less samples
        while len(population) < population_size and attempts < max_attempts:
            attempts += 1
            scenario = ScenarioFactory.generate_random_scenario(
                self.config, self.valid_scenarios
            )

            if scenario and scenario not in already_seen:
                population.append(scenario)
                already_seen.add(scenario)

        # If we could not generate enough unique scenarios, duplicate some samples
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
        # If scenario has already been run, do not run it again.
        # we will rely on mutation for the same parents to produce newer samples
        if scenario in self.seen_population:
            logger.info(
                "Scenario %s already evaluated, skipping fitness calculation.", scenario
            )
            result = self.seen_population[scenario]
            result = copy.deepcopy(result)
            result.generation_id = generation_id
            return result
        scenario_result = self.krkn_client.run(scenario, generation_id)

        # Add scenario to seen population
        self.seen_population[scenario] = scenario_result

        # Save scenario result
        self.save_scenario_result(scenario_result)
        self.health_check_reporter.plot_report(scenario_result)
        self.health_check_reporter.write_fitness_result(scenario_result)
        if self.elastic_client is not None:
            self.elastic_client.index_run_result(scenario_result, self.run_uuid)

        return scenario_result

    def mutate(self, scenario: BaseScenario):
        if isinstance(scenario, CompositeScenario):
            scenario.scenario_a = self.mutate(scenario.scenario_a)
            scenario.scenario_b = self.mutate(scenario.scenario_b)
            return scenario

        # Scenario mutation (new scenario, try to preserve properties)
        if rng.random() < self.config.scenario_mutation_rate:
            success, new_scenario = self.scenario_mutation(scenario)
            if success:
                # logger.debug("Scenario mutation successful")
                return new_scenario

        # Parameter mutation (current scenario, try to change properties)
        if hasattr(scenario, "mutate"):
            scenario.mutate()
        else:
            logger.warning("Scenario %s does not have mutate method", scenario)
        return scenario

    def scenario_mutation(self, scenario: BaseScenario):
        """
        Create a new scenario of different type while trying to preserve properties.
        """
        # check scenarios for common parameters
        common_scenarios = []
        for _, scenario_cls in self.valid_scenarios:
            # instantiate new scenario for a scenario type
            new_scenario = scenario_cls(
                cluster_components=self.config.cluster_components
            )

            common_params = set([type(x) for x in new_scenario.parameters]) & set(
                [type(x) for x in scenario.parameters]
            )
            # Do not consider the same scenario type for scenario mutation
            if len(common_params) > 0 and not isinstance(new_scenario, type(scenario)):
                common_scenarios.append(new_scenario)

        if len(common_scenarios) == 0:
            logger.debug("No common scenarios found, returning original scenario")
            return False, scenario

        # create a new scenario with the same parameters
        new_scenario = rng.choice(common_scenarios)

        # Identify common parameters and set them to the new scenario
        common_params = set([type(x) for x in new_scenario.parameters]) & set(
            [type(x) for x in scenario.parameters]
        )
        for param_type in common_params:
            # Get parameter value from original scenario
            param_value = self.__get_param_value(scenario, param_type)

            # Set parameter value for new scenario
            self.__set_param_value(new_scenario, param_type, param_value)

        return True, new_scenario

    # TODO: Implement a more sophisticated selection method like Tournament Selection for better noise tolerance in fitness scores
    def select_parents(self, fitness_scores: List[CommandRunResult]):
        """
        Selects two parents using Roulette Wheel Selection (proportionate selection).
        Higher fitness means higher chance of being selected.
        """
        raw = [x.fitness_result.fitness_score for x in fitness_scores]
        scenarios = [x.scenario for x in fitness_scores]

        min_f = min(raw)
        max_f = max(raw)

        # Normalize to positive range
        if max_f == min_f:
            shifted: List[float] = [1.0 for _ in raw]  # identical fitness
        else:
            shifted = [(f - min_f) / (max_f - min_f) + 1e-8 for f in raw]

        total_fitness = sum(shifted)

        if total_fitness == 0:  # Handle case where all fitness scores are zero
            return rng.choice(scenarios), rng.choice(scenarios)

        # Normalize fitness scores to get probabilities
        probabilities = [f / total_fitness for f in shifted]

        # Select parents based on probabilities
        parent1 = rng.choices(items=scenarios, weights=probabilities, k=1)[0]
        parent2 = rng.choices(items=scenarios, weights=probabilities, k=1)[0]
        return parent1, parent2

    def crossover(self, scenario_a: BaseScenario, scenario_b: BaseScenario):
        if isinstance(scenario_a, CompositeScenario) and isinstance(
            scenario_b, CompositeScenario
        ):
            # Handle both scenario are composite
            # by swapping one of the branches
            scenario_a.scenario_b, scenario_b.scenario_b = (
                scenario_b.scenario_b,
                scenario_a.scenario_b,
            )
            return scenario_a, scenario_b
        elif isinstance(scenario_a, CompositeScenario) or isinstance(
            scenario_b, CompositeScenario
        ):
            # Only one of them is composite
            if isinstance(scenario_a, CompositeScenario):
                # Scenario A is composite and B is not
                # Swap scenario_a's right node with scenario_b
                a_b = scenario_a.scenario_b
                scenario_a.scenario_b = scenario_b
                return scenario_a, a_b
            else:
                # Scenario B is composite and A is not
                # Swap scenario_a's right node with scenario_b
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
            # no common parameter, currenty we return parents as is and hope for mutation
            # adopt some different strategy
            return scenario_a, scenario_b
        else:
            # if there are common params, lets switch values between them
            for param_type in common_params:
                if rng.random() < self.config.crossover_rate:
                    # find index of param in list
                    a_value = self.__get_param_value(scenario_a, param_type)
                    b_value = self.__get_param_value(scenario_b, param_type)

                    # swap param values
                    self.__set_param_value(scenario_a, param_type, b_value)
                    self.__set_param_value(scenario_b, param_type, a_value)

            return scenario_a, scenario_b

    def composition(self, scenario_a: BaseScenario, scenario_b: BaseScenario):
        # combines two scenario to create a single composite scenario
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

    def save(self):
        """Save run results"""
        # TODO: Create a single result file (results.json) that contains summary of all the results
        self.generations_reporter.save_best_generations(self.best_of_generation)
        self.generations_reporter.save_best_generation_graph(self.best_of_generation)
        self.health_check_reporter.save_report(self.seen_population.values())
        self.health_check_reporter.sort_fitness_result_csv()

        # TODO: Send run summary to Elasticsearch

    def save_config(self):
        logger.info("Saving config file to config.yaml")
        output_dir = self.output_dir
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "krkn-ai.yaml"), "w", encoding="utf-8") as f:
            config_data = self.config.model_dump(mode="json")
            # exclude default values from cluster components
            config_data["cluster_components"] = (
                self.config.cluster_components.model_dump(
                    mode="json", exclude_defaults=True
                )
            )
            yaml.dump(config_data, f, sort_keys=False)

    def save_log_file(self, command_result: CommandRunResult):
        dir_path = os.path.join(self.output_dir, "logs")
        os.makedirs(dir_path, exist_ok=True)
        # Store log file in output directory under a "logs" folder.
        log_filename = format_result_filename(
            self.config.output.log_name_fmt, command_result
        )
        log_save_path = os.path.join(dir_path, log_filename)
        with open(log_save_path, "w", encoding="utf-8") as f:
            f.write(command_result.log)
        return log_save_path

    def save_scenario_result(self, fitness_result: CommandRunResult):
        logger.debug(
            "Saving scenario result for scenario %s", fitness_result.scenario_id
        )
        result = fitness_result.model_dump()
        scenario_name = fitness_result.scenario.name
        result["scenario"]["name"] = scenario_name
        generation_id = result["generation_id"]
        result["job_id"] = fitness_result.scenario_id

        # Store log in a log file and update log location
        result["log"] = self.save_log_file(fitness_result)
        # Convert timestamps to ISO string
        result["start_time"] = (result["start_time"]).isoformat()
        result["end_time"] = (result["end_time"]).isoformat()

        output_dir = os.path.join(
            self.output_dir, self.format, "generation_%s" % generation_id
        )
        os.makedirs(output_dir, exist_ok=True)

        # Format YAML filename using configured format
        filename = format_result_filename(
            self.config.output.result_name_fmt, fitness_result
        )
        # Ensure the extension matches the format
        if not filename.endswith(f".{self.format}"):
            # Remove any existing extension and add the correct one
            base_name = os.path.splitext(filename)[0]
            filename = f"{base_name}.{self.format}"

        with open(
            os.path.join(output_dir, filename), "w", encoding="utf-8"
        ) as file_handler:
            if self.format == "json":
                json.dump(result, file_handler, indent=4)
            elif self.format == "yaml":
                yaml.dump(result, file_handler, sort_keys=False)

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
