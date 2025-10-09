import os
import json
import datetime
import tempfile

from krkn_lib.prometheus.krkn_prometheus import KrknPrometheus
from krkn_ai.chaos_engines.health_check_watcher import HealthCheckWatcher
from krkn_ai.models.app import CommandRunResult, FitnessResult, FitnessScoreResult, KrknRunnerType
from krkn_ai.models.config import ConfigFile, FitnessFunctionType
from krkn_ai.models.scenario.base import Scenario, BaseScenario, CompositeDependency, CompositeScenario
from krkn_ai.models.scenario.factory import ScenarioFactory
from krkn_ai.utils import run_shell
from krkn_ai.utils.fs import env_is_truthy
from krkn_ai.utils.logger import get_module_logger
from krkn_ai.utils.rng import rng

logger = get_module_logger(__name__)

# TODO: Cleanup of temp kubeconfig after running the script

PODMAN_TEMPLATE = 'podman run --env-host=true -e PUBLISH_KRAKEN_STATUS="False" -e TELEMETRY_PROMETHEUS_BACKUP="False" -e WAIT_DURATION=0 {env_list} --net=host -v {kubeconfig}:/home/krkn/.kube/config:Z containers.krkn-chaos.dev/krkn-chaos/krkn-hub:{name}'

KRKNCTL_TEMPLATE = "krknctl run {name} --telemetry-prometheus-backup False --wait-duration 0 --kubeconfig {kubeconfig} {env_list}"

KRKNCTL_GRAPH_RUN_TEMPLATE = "krknctl graph run {path} --kubeconfig {kubeconfig}"

KRKN_HUB_FAILURE_SCORE = 5


class KrknRunner:
    def __init__(
        self,
        config: ConfigFile,
        output_dir: str,
        runner_type: KrknRunnerType = None,
    ):
        self.config = config
        self.prom_client = self.__connect_prom_client()
        self.output_dir = output_dir
        if runner_type is None:
            self.runner_type = self.__check_runner_availability()
        else:
            logger.debug("Using user provided runner type: %s", runner_type)
            self.runner_type = runner_type


    def __check_runner_availability(self):
        # Check if krknctl is available
        krknctl_available = True
        podman_available = True
        _, returncode = run_shell("krknctl --version", do_not_log=True)
        if returncode != 0:
            krknctl_available = False
            logger.warning("krknctl is not available.")
        
        # Check if podman is available
        _, returncode = run_shell("podman --version", do_not_log=True)
        if returncode != 0:
            podman_available = False
            logger.warning("podman is not available.")

        if krknctl_available is False and podman_available is False:
            raise Exception("krknctl and podman are not available. Please install krknctl and podman.")

        if krknctl_available:
            logger.debug("Using krknctl as runner.")
            return KrknRunnerType.CLI_RUNNER
        if podman_available:
            logger.debug("Using krknhub as runner.")
            return KrknRunnerType.HUB_RUNNER

    def run(self, scenario: BaseScenario, generation_id: int) -> CommandRunResult:
        logger.debug("Running scenario %s", scenario)

        start_time = datetime.datetime.now()

        # Generate command krkn executor command
        log, returncode = None, None
        command = ""
        if isinstance(scenario, CompositeScenario):
            command = self.graph_command(scenario)
        elif isinstance(scenario, Scenario):
            command = self.runner_command(scenario)
        else:
            raise NotImplementedError("Scenario unable to run")

        health_check_watcher = HealthCheckWatcher(self.config.health_checks)

        # Run command and fetch result
        if env_is_truthy('MOCK_RUN'):
            # Used for running mock tests
            log, returncode = "", 0
        else:
            # TODO: How to capture logs from composite run scenario
            
            # Start watching application urls for health checks
            health_check_watcher.run()

            # Run command
            log, returncode = run_shell(command)
            
            # Stop watching application urls for health checks
            health_check_watcher.stop()

        end_time = datetime.datetime.now()

        # calculate fitness scores
        fitness_result: FitnessResult = FitnessResult()

        # If user provided fitness_function.query, then we use the default function to calculate
        if self.config.fitness_function.query is not None:
            fitness_value = self.calculate_fitness_value(
                start=start_time,
                end=end_time,
                query=self.config.fitness_function.query,
                fitness_type=self.config.fitness_function.type
            )
            fitness_result.fitness_score = fitness_value
        elif len(self.config.fitness_function.items) > 0:
            fitness_result = self.calculate_fitness_score_for_items(
                start=start_time,
                end=end_time
            )

        health_check_results = health_check_watcher.get_results()

        # Include krkn hub run failure info to the fitness score
        if self.config.fitness_function.include_krkn_failure:
            # Status code 2 means that SLOs not met per Krkn test
            if returncode == 2:
                fitness_result.krkn_failure_score = KRKN_HUB_FAILURE_SCORE

        # Include health check failure and response time to the fitness score
        if self.config.fitness_function.include_health_check_failure:
            fitness_result.health_check_failure_score = health_check_watcher.summarize_success_rate(health_check_results)
        if self.config.fitness_function.include_health_check_response_time:
            fitness_result.health_check_response_time_score = health_check_watcher.summarize_response_time(health_check_results)

        # Calculate overall fitness score
        fitness_result.fitness_score = sum([
            fitness_result.fitness_score,
            fitness_result.krkn_failure_score,
            fitness_result.health_check_failure_score,
            fitness_result.health_check_response_time_score
        ])

        return CommandRunResult(
            generation_id=generation_id,
            scenario=scenario,
            cmd=command,
            log=log,
            returncode=returncode,
            start_time=start_time,
            end_time=end_time,
            fitness_result=fitness_result,
            health_check_results=health_check_results
        )

    def runner_command(self, scenario: Scenario):
        """Generate command for krkn runner (krknctl, krknhub)"""
        if self.runner_type == KrknRunnerType.HUB_RUNNER:
            # Generate env items
            env_list = ""
            for parameter in scenario.parameters:
                # we use parameter.name instead of parameter.get_name() because krknhub uses parameter.name
                env_list += f' -e {parameter.name}="{parameter.get_value()}" '

            command = PODMAN_TEMPLATE.format(
                env_list=env_list,
                kubeconfig=self.config.kubeconfig_file_path,
                name=scenario.name,
            )
            return command
        elif self.runner_type == KrknRunnerType.CLI_RUNNER:
            # Generate env parameters for scenario
            # krknctl the env parameter keys are small-casing, separated by hyphens
            # by default we use upper-casing, separated by underscore.
            env_list = ""
            for parameter in scenario.parameters:
                # TODO: This is a hack to make krknctl work. Probably need some unified naming convention for parameters.
                # We use parameter.get_name() because krknctl names can be different from parameter.name which is used mainly in Krknhub
                param_name = (parameter.get_name()).lower().replace("_", "-")
                env_list += f'--{param_name} "{parameter.get_value()}" '

            command = KRKNCTL_TEMPLATE.format(
                env_list=env_list,
                kubeconfig=self.config.kubeconfig_file_path,
                name=scenario.name,
            )
            return command
        raise Exception("Unsupported runner type")

    def graph_command(self, scenario: CompositeScenario):
        # Create directory under output folder to save CompositeScenario config
        graph_json_directory = os.path.join(self.output_dir, "graphs")
        os.makedirs(graph_json_directory, exist_ok=True)

        # Create JSON for krknctl graph runner
        scenario_json = self.__expand_composite_json(scenario)
        json_file = tempfile.mktemp(suffix=".json", dir=graph_json_directory)
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(scenario_json, f, ensure_ascii=False, indent=4)
        logger.info("Created scenario json in path: %s", json_file)

        # Run Json graph
        command = KRKNCTL_GRAPH_RUN_TEMPLATE.format(
            path=json_file, kubeconfig=self.config.kubeconfig_file_path
        )
        return command

    def __expand_composite_json(
        self,
        scenario: CompositeScenario,
        root: str = "$",
        depends_on: str = None
    ):
        result = {}
        scenario_a = scenario.scenario_a
        scenario_b = scenario.scenario_b

        key_root = root
        key_a = root + "l"
        key_b = root + "r"

        # Create a dummy scenario which will be the root for scenario A and B.
        if scenario.dependency == CompositeDependency.NONE:
            result[key_root] = self.__generate_scenario_json(
                ScenarioFactory.create_dummy_scenario(),
                depends_on=depends_on
            )

        # Generate json for scenario A
        if isinstance(scenario_a, CompositeScenario):
            # Generate Dependency Key
            key = None
            if scenario.dependency == CompositeDependency.A_ON_B:
                key = key_b
            elif scenario.dependency == CompositeDependency.B_ON_A:
                key = depends_on
            elif scenario.dependency == CompositeDependency.NONE:
                key = key_root

            # Since we are traversing left of the tree, key_a will contain the unique parent id 
            result.update(self.__expand_composite_json(scenario_a, key_a, depends_on=key))
        elif isinstance(scenario_a, Scenario):
            key = None
            if scenario.dependency == CompositeDependency.A_ON_B:
                key = key_b
            elif scenario.dependency == CompositeDependency.B_ON_A:
                key = depends_on
            elif scenario.dependency == CompositeDependency.NONE:
                key = key_root

            result[key_a] = self.__generate_scenario_json(
                scenario_a,
                depends_on=key,
            )

        # Generate json for scenario B
        if isinstance(scenario_b, CompositeScenario):
            key = None
            if scenario.dependency == CompositeDependency.A_ON_B:
                key = depends_on
            elif scenario.dependency == CompositeDependency.B_ON_A:
                key = key_b
            elif scenario.dependency == CompositeDependency.NONE:
                key = key_root

            # Since we are traversing right of the tree, key_b will contain the unique parent id
            result.update(self.__expand_composite_json(scenario_b, key_b, depends_on=key))
        elif isinstance(scenario_b, Scenario):
            key = None
            if scenario.dependency == CompositeDependency.A_ON_B:
                key = depends_on
            elif scenario.dependency == CompositeDependency.B_ON_A:
                key = key_a
            elif scenario.dependency == CompositeDependency.NONE:
                key = key_root
            result[key_b] = self.__generate_scenario_json(
                scenario_b,
                depends_on=key,
            )

        return result

    def __generate_scenario_json(self, scenario: Scenario, depends_on: str = None):
        # generate a json based on https://krkn-chaos.dev/docs/krknctl/randomized-chaos-testing/#example
        env = {param.name: str(param.get_value()) for param in scenario.parameters}
        result = {
            "image": f"containers.krkn-chaos.dev/krkn-chaos/krkn-hub:{scenario.name}",
            "name": scenario.name,
            "env": env,
        }
        if depends_on is not None:
            result["depends_on"] = depends_on
        return result

    def __connect_prom_client(self):
        # Fetch Prometheus query endpoint
        url = os.getenv("PROMETHEUS_URL", "")
        if url == "":
            prom_spec_json, _ = run_shell(
                f"kubectl --kubeconfig={self.config.kubeconfig_file_path} -n openshift-monitoring get route -l app.kubernetes.io/name=thanos-query -o json",
                do_not_log=True,
            )
            prom_spec_json = json.loads(prom_spec_json)
            url = prom_spec_json["items"][0]["spec"]["host"]

        # Fetch K8s token to access internal service
        token = os.getenv("PROMETHEUS_TOKEN", "")
        if token == "":
            token, _ = run_shell(
                f"oc --kubeconfig={self.config.kubeconfig_file_path} whoami -t",
                do_not_log=True,
            )

        logger.debug("Prometheus URL: %s", url)

        return KrknPrometheus(f"https://{url}", token.strip())

    def calculate_fitness_value(self, start, end, query, fitness_type):
        """Calculate fitness score for scenario run"""
        if env_is_truthy("MOCK_FITNESS"):
            return rng.random()

        try:
            if fitness_type == FitnessFunctionType.point:
                return self.calculate_point_fitness(start, end, query)
            elif fitness_type == FitnessFunctionType.range:
                return self.calculate_range_fitness(start, end, query)
        except Exception as error:
            logger.error("Fitness function calculation failed: %s", error)
            raise error

    def calculate_fitness_score_for_items(self, start, end):
        '''
        This is used to compute fitness scores when multiple SLOs are defined.
        '''
        results = []
        overall_score = 0
        for fitness_item in self.config.fitness_function.items:
            raw_score = self.calculate_fitness_value(
                start=start,
                end=end,
                query=fitness_item.query,
                fitness_type=fitness_item.type
            )
            fitness_value = fitness_item.weight * raw_score
            overall_score += fitness_value

            # Store Result
            results.append(FitnessScoreResult(
                id=fitness_item.id,
                fitness_score=raw_score,
                weighted_score=fitness_value
            ))

        return FitnessResult(
            fitness_score=overall_score,
            scores=results
        )

    def calculate_point_fitness(self, start, end, query):
        """Takes difference between fitness function at start/end intervals of test.
        Helpful to measure values for counter based metric like restarts.
        """
        logger.debug("Calculating Point Fitness")
        result_at_beginning = self.prom_client.process_prom_query_in_range(
            query,
            start_time=start,
            end_time=start,
            granularity=100,
        )[0]["values"][-1][1]

        result_at_end = self.prom_client.process_prom_query_in_range(
            query,
            start_time=end,
            end_time=end,
            granularity=100,
        )[0]["values"][-1][1]

        return float(result_at_end) - float(result_at_beginning)

    def calculate_range_fitness(self, start, end, query):
        """
        Measure fitness function for the range of test.
        Helpful to measure value over period of time like max cpu usage, max memory usage over time, etc.

        config.fitness_function.query can specify a dynamic "$range$" parameter that will be replaced
        when calling below function.
        """
        logger.debug("Calculating Range Fitness")

        # Calculate number of minutes between test run
        if "$range$" in query:
            time_dt_mins = int((end - start).total_seconds() / 60)
            if time_dt_mins == 0:
                time_dt_mins = 1
            query = query.replace("$range$", f"{time_dt_mins}m")
        else:
            logger.warning(
                "You are missing $range$ in config.fitness_function.query to specify dynamic range. Fitness function will use specified range"
            )

        result = self.prom_client.process_prom_query_in_range(
            query,
            start_time=start,
            end_time=end,
            granularity=100,
        )[0]["values"][-1][1]

        return float(result)
