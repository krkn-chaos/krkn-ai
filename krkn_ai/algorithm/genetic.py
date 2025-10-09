import os
import copy
import json
import yaml
from typing import List

from krkn_ai.models.app import CommandRunResult, KrknRunnerType

from krkn_ai.models.scenario.base import Scenario, BaseScenario, CompositeDependency, CompositeScenario
from krkn_ai.models.scenario.factory import ScenarioFactory

from krkn_ai.models.config import ConfigFile
from krkn_ai.reporter.generations_reporter import GenerationsReporter
from krkn_ai.reporter.health_check_reporter import HealthCheckReporter
from krkn_ai.utils.logger import get_module_logger
from krkn_ai.chaos_engines.krkn_runner import KrknRunner
from krkn_ai.utils.rng import rng
from krkn_ai.models.custom_errors import PopulationSizeError

logger = get_module_logger(__name__)


class GeneticAlgorithm:
    '''
    A class implementing a Genetic Algorithm for scenario optimization.
    '''
    def __init__(self, 
        config: ConfigFile, 
        output_dir: str,
        format: str,
        runner_type: KrknRunnerType = None
    ):
        self.krkn_client = KrknRunner(
            config,
            output_dir=output_dir,
            runner_type=runner_type
        )
        self.output_dir = output_dir
        self.config = config
        self.population = []
        self.format = format

        self.seen_population = {}  # Map between scenario and its result
        self.best_of_generation = []

        self.health_check_reporter = HealthCheckReporter(self.output_dir)
        self.generations_reporter = GenerationsReporter(self.output_dir, self.format)

        if self.config.population_size < 2:
            raise PopulationSizeError("Population size should be at least 2")

        # Population size should be even
        if self.config.population_size % 2 != 0:
            logger.debug("Population size is odd, making it even for the genetic algorithm.")
            self.config.population_size += 1

        logger.debug("CONFIG")
        logger.debug("--------------------------------------------------------")
        logger.debug("%s", json.dumps(self.config.model_dump(), indent=2))

    def simulate(self):
        self.create_population(self.config.population_size)

        for i in range(self.config.generations):
            if len(self.population) == 0:
                logger.warning("No more population found, stopping generations.")
                break

            logger.info("| Population |")
            logger.info("--------------------------------------------------------")
            for scenario in self.population:
                logger.info("%s, ", scenario)
            logger.info("--------------------------------------------------------")

            logger.info("| Generation %d |", i + 1)
            logger.info("--------------------------------------------------------")

            # Evaluate fitness of the current population
            fitness_scores = [
                self.calculate_fitness(member, i) for member in self.population
            ]
            # Find the best individual in the current generation
            # Note: If there is no best solution, it will still consider based on sorting order
            fitness_scores = sorted(
                fitness_scores, key=lambda x: x.fitness_result.fitness_score, reverse=True
            )
            self.best_of_generation.append(fitness_scores[0])
            logger.info("Best Fitness: %f", fitness_scores[0].fitness_result.fitness_score)

            # We don't want to add a same parent back to population since its already been included
            for fitness_result in fitness_scores:
                self.seen_population[fitness_result.scenario] = fitness_result

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
                self.create_population(self.config.population_injection_size)

    def create_population(self, population_size):
        """Generate random population for algorithm"""
        logger.info("Creating random population")
        logger.info("Population Size: %d", self.config.population_size)

        already_seen = set()
        count = 0
        while count != population_size:
            scenario = ScenarioFactory.generate_random_scenario(self.config)
            if scenario and scenario not in already_seen:
                self.population.append(scenario)
                already_seen.add(scenario)
                count += 1


    def calculate_fitness(self, scenario: BaseScenario, generation_id: int):
        # If scenario has already been run, do not run it again.
        # we will rely on mutation for the same parents to produce newer samples
        if scenario in self.seen_population:
            logger.info("Scenario %s already evaluated, skipping fitness calculation.", scenario)
            scenario = copy.deepcopy(self.seen_population[scenario])
            scenario.generation_id = generation_id
            return scenario
        scenario_result = self.krkn_client.run(scenario, generation_id)
        # Save scenario result
        self.save_scenario_result(scenario_result)
        self.health_check_reporter.plot_report(scenario_result)
        self.health_check_reporter.write_fitness_result(scenario_result)
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
        '''
        Create a new scenario of different type while trying to preserve properties.
        '''
        possible_scenarios = ScenarioFactory.list_scenarios(self.config)

        # check scenarios for common parameters
        common_scenarios = []
        for _, scenario_cls in possible_scenarios:
            # instantiate new scenario for a scenario type
            new_scenario = scenario_cls(cluster_components=self.config.cluster_components)

            common_params = set([x.name for x in new_scenario.parameters]) & set(
                [x.name for x in scenario.parameters]
            )
            # Do not consider the same scenario type for scenario mutation
            if len(common_params) > 0 and type(new_scenario) != type(scenario):
                common_scenarios.append(new_scenario)
        if len(common_scenarios) == 0:
            logger.warning("No common scenarios found, returning original scenario")
            return False, scenario

        # create a new scenario with the same parameters
        new_scenario = rng.choice(common_scenarios)

        # Identify common parameters and set them to the new scenario
        common_params = set([x.name for x in new_scenario.parameters]) & set([x.name for x in scenario.parameters])
        for param in common_params:
            # Get parameter value from original scenario
            param_value = self.__get_param_value(scenario, param)

            # Set parameter value for new scenario
            self.__set_param_value(new_scenario, param, param_value)

        return True, new_scenario


    def select_parents(self, fitness_scores: List[CommandRunResult]):
        """
        Selects two parents using Roulette Wheel Selection (proportionate selection).
        Higher fitness means higher chance of being selected.
        """
        total_fitness = sum([x.fitness_result.fitness_score for x in fitness_scores])

        scenarios = [x.scenario for x in fitness_scores]

        if total_fitness == 0:  # Handle case where all fitness scores are zero
            return rng.choice(scenarios), rng.choice(scenarios)

        # Normalize fitness scores to get probabilities
        probabilities = [x.fitness_result.fitness_score / total_fitness for x in fitness_scores]

        # Select parents based on probabilities
        parent1 = rng.choices(items=scenarios, weights=probabilities, k=1)[0]
        parent2 = rng.choices(items=scenarios, weights=probabilities, k=1)[0]
        return parent1, parent2

    def crossover(self, scenario_a: BaseScenario, scenario_b: BaseScenario):
        if isinstance(scenario_a, CompositeScenario) and isinstance(scenario_b, CompositeScenario):
            # Handle both scenario are composite
            # by swapping one of the branches
            scenario_a.scenario_b, scenario_b.scenario_b = scenario_b.scenario_b, scenario_a.scenario_b
            return scenario_a, scenario_b
        elif isinstance(scenario_a, CompositeScenario) or isinstance(scenario_b, CompositeScenario):
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

        if not hasattr(scenario_a, "parameters") or not hasattr(scenario_b, "parameters"):
            logger.warning("Scenario %s or %s does not have property 'parameters'", scenario_a, scenario_b)
            return scenario_a, scenario_b

        common_params = set([x.name for x in scenario_a.parameters]) & set(
            [x.name for x in scenario_b.parameters]
        )

        if len(common_params) == 0:
            # no common parameter, currenty we return parents as is and hope for mutation
            # adopt some different strategy
            return scenario_a, scenario_b
        else:
            # if there are common params, lets switch values between them
            for param in common_params:
                if rng.random() < self.config.crossover_rate:
                    # find index of param in list
                    a_value = self.__get_param_value(scenario_a, param)
                    b_value = self.__get_param_value(scenario_b, param)

                    # swap param values
                    self.__set_param_value(scenario_a, param, b_value)
                    self.__set_param_value(scenario_b, param, a_value)

            return scenario_a, scenario_b

    def composition(self, scenario_a: BaseScenario, scenario_b: BaseScenario):
        # combines two scenario to create a single composite scenario
        dependency = rng.choice([
            CompositeDependency.NONE,
            CompositeDependency.A_ON_B,
            CompositeDependency.B_ON_A
        ])
        composite_scenario = CompositeScenario(
            name="composite",
            scenario_a=scenario_a,
            scenario_b=scenario_b,
            dependency=dependency
        )
        return composite_scenario

    def save(self):
        '''Save run results'''
        # TODO: Create a single result file (results.json) that contains summary of all the results
        self.save_config()
        self.generations_reporter.save_best_generations(self.best_of_generation)
        self.generations_reporter.save_best_generation_graph(self.best_of_generation)
        self.health_check_reporter.save_report(self.seen_population.values())

    def save_config(self):
        logger.info("Saving config file to config.yaml")
        output_dir = self.output_dir
        os.makedirs(output_dir, exist_ok=True)
        with open(
            os.path.join(output_dir, "krkn-ai.yaml"),
            "w",
            encoding="utf-8"
        ) as f:
            config_data = self.config.model_dump(mode='json')
            yaml.dump(config_data, f, sort_keys=False)

    def save_log_file(self, job_id: str, log_data: str):
        dir_path = os.path.join(self.output_dir, 'logs')
        os.makedirs(dir_path, exist_ok=True)
        # Store log file in output directory under a "logs" folder.
        log_save_path = os.path.join(dir_path, "scenario_%s.log" % job_id)
        with open(log_save_path, 'w', encoding='utf-8') as f:
            f.write(log_data)
        return log_save_path

    def save_scenario_result(self, fitness_result: CommandRunResult):
        logger.debug("Saving scenario result for scenario %s", fitness_result.scenario_id)
        result = fitness_result.model_dump()
        # Convert scenario to string representation and replace it in scenario.name
        result['scenario']['name'] = str(fitness_result.scenario)
        generation_id = result['generation_id']
        result['job_id'] = fitness_result.scenario_id

        # Store log in a log file and update log location
        result['log'] = self.save_log_file(
            str(fitness_result.scenario_id),
            result['log']
        )
        # Convert timestamps to ISO string
        result['start_time'] = (result['start_time']).isoformat()
        result['end_time'] = (result['end_time']).isoformat()

        output_dir = os.path.join(self.output_dir, self.format, "generation_%s" % generation_id)
        os.makedirs(output_dir, exist_ok=True)

        with open(
                os.path.join(output_dir, "scenario_%s.%s" % (fitness_result.scenario_id, self.format)),
                "w",
                encoding="utf-8"
            ) as file_handler:
                if self.format == 'json':
                    json.dump(result, file_handler, indent=4)
                elif self.format == 'yaml':
                    yaml.dump(result, file_handler, sort_keys=False)

    def __get_param_value(self, scenario: Scenario, param_name):
        for param in scenario.parameters:
            if param_name == param.name:
                return param.value
        raise ValueError(f"Parameter {param_name} not found in scenario {scenario}")

    def __set_param_value(self, scenario: Scenario, param_name, value):
        for param in scenario.parameters:
            if param_name == param.name:
                param.value = value
                return
