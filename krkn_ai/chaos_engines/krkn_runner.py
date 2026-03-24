import os
import json
import datetime
import tempfile
import time
from typing import Optional, Tuple

from krkn_ai.chaos_engines.health_check_watcher import HealthCheckWatcher
from krkn_ai.models.app import (
    CommandRunResult,
    FitnessResult,
    FitnessScoreResult,
    KrknRunnerType,
)
from krkn_ai.models.config import ConfigFile, FitnessFunctionType
from krkn_ai.models.custom_errors import FitnessFunctionCalculationError
from krkn_ai.models.scenario.base import (
    Scenario,
    BaseScenario,
    CompositeDependency,
    CompositeScenario,
)
from krkn_ai.models.scenario.factory import ScenarioFactory
from krkn_ai.utils import run_shell
from krkn_ai.utils.fs import env_is_truthy
from krkn_ai.utils.logger import get_logger, is_verbose
from krkn_ai.utils.prometheus import create_prometheus_client
from krkn_ai.utils.rng import rng

logger = get_logger(__name__)

# TODO: Cleanup of temp kubeconfig after running the script

PODMAN_TEMPLATE = 'podman run --env-host=true -e PUBLISH_KRAKEN_STATUS="False" -e TELEMETRY_PROMETHEUS_BACKUP="False" -e WAIT_DURATION={wait_duration} {env_list} {{es_env_list}} --net=host -v {kubeconfig}:/home/krkn/.kube/config:Z {image}'

PODMAN_ES_TEMPLATE = ' -e ENABLE_ES="True" -e ES_SERVER="{server}" -e ES_PORT="{port}" -e ES_USERNAME="{username}" -e ES_PASSWORD="{password}" -e ES_VERIFY_CERTS="{verify_certs}" '

KRKNCTL_TEMPLATE = "krknctl run {name} --telemetry-prometheus-backup False --wait-duration {wait_duration} --kubeconfig {kubeconfig} {env_list} {{es_env_list}}"

KRKNCTL_ES_TEMPLATE = ' --enable-es True --es-server "{server}" --es-port "{port}" --es-username "{username}" --es-password "{password}" --es-verify-certs "{verify_certs}" '

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
        self.prom_client = create_prometheus_client(self.config.kubeconfig_file_path)
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
            raise Exception(
                "krknctl and podman are not available. Please install krknctl and podman."
            )

        if krknctl_available:
            logger.debug("Using krknctl as runner.")
            return KrknRunnerType.CLI_RUNNER
        if podman_available:
            logger.debug("Using krknhub as runner.")
            return KrknRunnerType.HUB_RUNNER

    def run(self, scenario: BaseScenario, generation_id: int) -> CommandRunResult:
        logger.info("Running scenario: %s", scenario)

        start_time = datetime.datetime.now()
        mono_start = time.monotonic()

        # Generate command krkn executor command
        log, returncode, run_uuid = None, None, None
        command = ""
        if isinstance(scenario, CompositeScenario):
            command = self.graph_command(scenario)
        elif isinstance(scenario, Scenario):
            command = self.runner_command(scenario)
        else:
            raise NotImplementedError("Scenario unable to run")

        health_check_watcher = HealthCheckWatcher(self.config.health_checks)

        # Run command and fetch result
        if env_is_truthy("MOCK_RUN"):
            # Used for running mock tests
            time.sleep(rng.randint(1, 3))
            log, returncode = "", 0
        else:
            # TODO: How to capture logs from composite run scenario

            # Start watching application urls for health checks
            health_check_watcher.run()

            try:
                # Run command (show logs when verbose mode is enabled)
                log, returncode = run_shell(
                    self.process_es_env_string(command, True),
                    do_not_log=not is_verbose(),
                )

                # Extract return code from run log which is part of telemetry data present in the log
                returncode, run_uuid = self.__extract_returncode_from_run(
                    log, returncode
                )
                logger.info("Krkn scenario return code: %d", returncode)

            finally:
                # Stop watching application urls for health checks
                health_check_watcher.stop()

        end_time = datetime.datetime.now()
        duration_seconds = time.monotonic() - mono_start

        # calculate fitness scores
        fitness_result: FitnessResult = FitnessResult()

        health_check_results = health_check_watcher.get_results()

        # Check if krkn scenario failed due to misconfiguration (non-zero and not status code 2)
        # Status code 2 means that SLOs not met per Krkn test (valid failure)
        # Other non-zero status codes indicate misconfiguration errors
        if returncode != 0 and returncode != 2:
            # Misconfiguration failure - skip fitness calculation and set failure marker
            logger.warning(
                "Krkn scenario failed with return code %d (misconfiguration). "
                "Skipping fitness calculation to avoid data pollution.",
                returncode,
            )
            if self.config.fitness_function.include_krkn_failure:
                fitness_result.krkn_failure_score = -1.0
            fitness_result.fitness_score = -1.0
            logger.info("Fitness score set to -1 due to misconfiguration failure")
        else:
            # Normal execution path - calculate fitness scores
            # If user provided fitness_function.query, then we use the default function to calculate
            if self.config.fitness_function.query is not None:
                fitness_value = self.calculate_fitness_value(
                    start=start_time,
                    end=end_time,
                    query=self.config.fitness_function.query,
                    fitness_type=self.config.fitness_function.type,
                )
                fitness_result.fitness_score = fitness_value
            elif len(self.config.fitness_function.items) > 0:
                fitness_result = self.calculate_fitness_score_for_items(
                    start=start_time, end=end_time
                )

            # Include krkn hub run failure info to the fitness score
            if self.config.fitness_function.include_krkn_failure:
                # Status code 2 means that SLOs not met per Krkn test
                if returncode == 2:
                    fitness_result.krkn_failure_score = KRKN_HUB_FAILURE_SCORE

            # Include health check failure and response time to the fitness score
            if self.config.fitness_function.include_health_check_failure:
                fitness_result.health_check_failure_score = (
                    health_check_watcher.summarize_success_rate(health_check_results)
                )
            if self.config.fitness_function.include_health_check_response_time:
                fitness_result.health_check_response_time_score = (
                    health_check_watcher.summarize_response_time(health_check_results)
                )

            # Calculate overall fitness score
            logger.debug("Fitness result: %s", fitness_result)
            fitness_result.fitness_score = sum(
                [
                    fitness_result.fitness_score,
                    fitness_result.krkn_failure_score,
                    fitness_result.health_check_failure_score,
                    fitness_result.health_check_response_time_score,
                ]
            )
            logger.info("Fitness score: %s", fitness_result.fitness_score)

        return CommandRunResult(
            generation_id=generation_id,
            scenario=scenario,
            cmd=self.process_es_env_string(command, False),
            log=log,
            returncode=returncode,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration_seconds,
            fitness_result=fitness_result,
            health_check_results=health_check_results,
            run_uuid=run_uuid,
        )

    def runner_command(self, scenario: Scenario):
        """Generate command for krkn runner (krknctl, krknhub)"""
        if self.runner_type == KrknRunnerType.HUB_RUNNER:
            # Generate env items
            env_list = ""
            for parameter in scenario.parameters:
                env_list += f' -e {parameter.get_name(return_krknhub_name=True)}="{parameter.get_value()}" '

            command = PODMAN_TEMPLATE.format(
                wait_duration=self.config.wait_duration,
                env_list=env_list,
                kubeconfig=self.config.kubeconfig_file_path,
                image=scenario.krknhub_image,
            )
            return command
        elif self.runner_type == KrknRunnerType.CLI_RUNNER:
            # Generate env parameters for scenario
            # krknctl the env parameter keys are small-casing, separated by hyphens
            env_list = ""
            for parameter in scenario.parameters:
                param_name = parameter.get_name(return_krknhub_name=False)
                env_list += f'--{param_name} "{parameter.get_value()}" '

            command = KRKNCTL_TEMPLATE.format(
                wait_duration=self.config.wait_duration,
                env_list=env_list,
                kubeconfig=self.config.kubeconfig_file_path,
                name=scenario.krknctl_name,
            )
            return command
        raise Exception("Unsupported runner type")

    def process_es_env_string(self, command: str, enable: bool):
        # Patch Elasticsearch (ES) configuration into runner command for Krknctl or KrknHub

        if (
            not enable
            or self.config.elastic is None
            or self.config.elastic.enable is False
        ):
            # If ES is not enabled, remove the ES environment placeholder
            return command.replace("{es_env_list}", "")

        es_env_list = ""
        if self.runner_type == KrknRunnerType.HUB_RUNNER:
            es_env_list = PODMAN_ES_TEMPLATE.format(
                server=self.config.elastic.server,
                port=self.config.elastic.port,
                username=self.config.elastic.username,
                password=self.config.elastic.password,
                verify_certs=self.config.elastic.verify_certs,
            )
        elif self.runner_type == KrknRunnerType.CLI_RUNNER:
            es_env_list = KRKNCTL_ES_TEMPLATE.format(
                server=self.config.elastic.server,
                port=self.config.elastic.port,
                username=self.config.elastic.username,
                password=self.config.elastic.password,
                verify_certs=self.config.elastic.verify_certs,
            )

        return command.replace("{es_env_list}", es_env_list)

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
        self, scenario: CompositeScenario, root: str = "$", depends_on: str = None
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
                ScenarioFactory.create_dummy_scenario(), depends_on=depends_on
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
            result.update(
                self.__expand_composite_json(scenario_a, key_a, depends_on=key)
            )
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
            result.update(
                self.__expand_composite_json(scenario_b, key_b, depends_on=key)
            )
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
        # It uses krknhub env naming to define test parameters.
        env = {
            param.get_name(return_krknhub_name=True): str(param.get_value())
            for param in scenario.parameters
        }
        result = {
            "image": scenario.krknhub_image,
            "name": scenario.name,
            "env": env,
        }
        if depends_on is not None:
            result["depends_on"] = depends_on
        return result

    def calculate_fitness_value(self, start, end, query, fitness_type):
        """Calculate fitness score for scenario run"""
        if env_is_truthy("MOCK_FITNESS"):
            return rng.random()

        # Retry to calculate fitness function if it fails
        # Case when data isn't available in prometheus for latest time range
        retries = 3  # Number of retries to calculate fitness function
        retry_delay = 10  # in seconds
        for retry in range(retries):
            try:
                if fitness_type == FitnessFunctionType.point:
                    return self.calculate_point_fitness(start, end, query)
                elif fitness_type == FitnessFunctionType.range:
                    return self.calculate_range_fitness(start, end, query)
            except Exception as error:
                logger.error(f"Fitness function calculation failed: {error}")
                logger.info(
                    f"Retrying fitness function calculation... (retry {retry + 1} of {retries})"
                )
                time.sleep(retry_delay)
        raise FitnessFunctionCalculationError(
            f"Fitness function calculation failed after {retries} retries"
        )

    def calculate_fitness_score_for_items(self, start, end):
        """
        This is used to compute fitness scores when multiple SLOs are defined.
        """
        results = []
        overall_score = 0
        for fitness_item in self.config.fitness_function.items:
            raw_score = self.calculate_fitness_value(
                start=start,
                end=end,
                query=fitness_item.query,
                fitness_type=fitness_item.type,
            )
            fitness_value = fitness_item.weight * raw_score
            overall_score += fitness_value

            # Store Result
            results.append(
                FitnessScoreResult(
                    id=fitness_item.id,
                    fitness_score=raw_score,
                    weighted_score=fitness_value,
                )
            )

        return FitnessResult(fitness_score=overall_score, scores=results)

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

    def __extract_returncode_from_run(
        self, log: str, default_returncode: int
    ) -> Tuple[int, Optional[str]]:
        """
        Try to extracts Krkn return code and uuid from the run log. If extraction fails, return default_returncode.
        """
        try:
            # TODO: Look into if we can save telemetry data to file from Krkn itself.
            # Hacky way to extract return code from log
            # Find the line with "Chaos data:" and extract JSON from next lines
            lines = log.split("\n")
            chaos_data_idx = -1

            for i, line in enumerate(lines):
                if "Chaos data:" in line:
                    chaos_data_idx = i + 1
                    break

            if chaos_data_idx == -1:
                logger.warning("Could not find 'Chaos data:' in log")
                return default_returncode, None

            # Extract JSON by counting braces
            json_lines = []
            brace_count = 0
            started = False

            for i in range(chaos_data_idx, len(lines)):
                line = lines[i]

                # Count opening and closing braces
                for char in line:
                    if char == "{":
                        brace_count += 1
                        started = True
                    elif char == "}":
                        brace_count -= 1

                if started:
                    json_lines.append(line)

                # When braces are balanced, we've found the complete JSON
                if started and brace_count == 0:
                    break

            if not json_lines:
                logger.warning("Could not extract JSON content from log")
                return default_returncode, None

            # Join all JSON lines into a single string
            json_str = "\n".join(json_lines)
            chaos_data = json.loads(json_str)

            # Extract exit_status from first scenario
            scenarios = chaos_data.get("telemetry", {}).get("scenarios", [])
            if scenarios and len(scenarios) > 0:
                exit_status = scenarios[0].get("exit_status", default_returncode)
                run_uuid = chaos_data.get("telemetry", {}).get("run_uuid", None)
                logger.debug("Extracted exit_status: %s", exit_status)
                logger.debug("Extracted run_uuid: %s", run_uuid)
                return exit_status, run_uuid

            logger.warning("No exit_status found in telemetry data")
            return default_returncode, None

        except Exception as e:
            logger.error("Failed to extract return code from run log: %s", e)
            return default_returncode, None
