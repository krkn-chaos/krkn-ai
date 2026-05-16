import os
import json  # Standard JSON library
import datetime
import tempfile
import time
from typing import Optional, Tuple, List

from krkn_ai.chaos_engines.health_check_watcher import HealthCheckWatcher
from krkn_ai.models.app import (
    CommandRunResult,
    FitnessResult,
    FitnessScoreResult,
    KrknRunnerType,
)
from krkn_ai.models.config import ConfigFile, HealthCheckResult
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

from krkn_ai.fitness.base import BaseFitnessEvaluator
from krkn_ai.fitness.prometheus import PrometheusEvaluator
from krkn_ai.fitness.health_check import HealthCheckEvaluator
from krkn_ai.fitness.python_script import PythonScriptEvaluator
from krkn_ai.fitness.aggregator import WeightedAggregator

logger = get_logger(__name__)

# TODO: Cleanup of temp kubeconfig after running the script

PODMAN_TEMPLATE = 'podman run -e PUBLISH_KRAKEN_STATUS="False" -e TELEMETRY_PROMETHEUS_BACKUP="False" -e WAIT_DURATION={wait_duration} {env_list} {{es_env_list}} --net=host -v {kubeconfig}:/home/krkn/.kube/config:Z {image}'

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

        self.evaluator = self._initialize_evaluators()

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

    def _initialize_evaluators(self) -> WeightedAggregator:
        """Initialize all configured fitness evaluators."""
        evaluators: List[Tuple[BaseFitnessEvaluator, float]] = []
        cfg = self.config.fitness_function

        # 1. Migrate legacy 'items' to PrometheusEvaluator (takes precedence)
        if cfg.items:
            for item in cfg.items:
                evaluators.append(
                    (
                        PrometheusEvaluator(self.prom_client, item.query, item.type),
                        item.weight,
                    )
                )
        # 2. Migrate legacy 'query' only if items are not defined
        elif cfg.query:
            evaluators.append(
                (PrometheusEvaluator(self.prom_client, cfg.query, cfg.type), 1.0)
            )

        # 3. Migrate legacy health check flags
        if cfg.include_health_check_failure:
            evaluators.append((HealthCheckEvaluator(mode="success_rate"), 1.0))
        if cfg.include_health_check_response_time:
            evaluators.append((HealthCheckEvaluator(mode="response_time"), 1.0))

        # 4. Add new pluggable evaluators
        for eval_cfg in cfg.evaluators:
            if eval_cfg.type == "prometheus":
                # Mypy: PrometheusEvaluator requires non-optional query and type
                assert eval_cfg.query is not None
                assert eval_cfg.fitness_type is not None
                evaluators.append(
                    (
                        PrometheusEvaluator(
                            self.prom_client, eval_cfg.query, eval_cfg.fitness_type
                        ),
                        eval_cfg.weight,
                    )
                )
            elif eval_cfg.type == "health_check":
                # Mypy: mode is optional in model but required by evaluator
                assert eval_cfg.mode is not None
                evaluators.append(
                    (HealthCheckEvaluator(mode=eval_cfg.mode), eval_cfg.weight)
                )
            elif eval_cfg.type == "python_script":
                # Mypy: script_path is optional in model but required here
                assert eval_cfg.script_path is not None
                evaluators.append(
                    (
                        PythonScriptEvaluator(script_path=eval_cfg.script_path),
                        eval_cfg.weight,
                    )
                )

        return WeightedAggregator(evaluators)

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

        health_check_watcher = HealthCheckWatcher(
            self.config.health_checks, self.config.parameters
        )

        # Run command and fetch result
        if env_is_truthy("MOCK_RUN"):
            # Used for running mock tests
            time.sleep(rng.randint(1, 3))
            log, returncode = "", 0
        else:
            try:
                # Start watching application urls for health checks
                health_check_watcher.run()

                # Run command (show logs when verbose mode is enabled)
                log, returncode = run_shell(
                    self.process_es_env_string(command, True),
                    do_not_log=not is_verbose(),
                )

                # Extract return code from run log which is part of telemetry data present in the log
                if isinstance(scenario, CompositeScenario):
                    # Use the return-code from the shell command for composite scenario
                    pass
                else:
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
            # Normal execution path - calculate fitness scores using pluggable engine
            context = {
                "health_check_results": health_check_results,
                "log": log,
                "returncode": returncode,
                "run_uuid": run_uuid,
                "scenario": scenario,
            }

            # If mock mode and no results, provide dummy data to avoid 'ignored' scores
            if (
                env_is_truthy("MOCK_RUN")
                and not health_check_results
                and self.config.health_checks.applications
            ):
                context["health_check_results"] = {
                    app.url: [
                        HealthCheckResult(
                            name=app.name,
                            status_code=app.status_code,
                            success=True,
                            response_time=0.1,
                        )
                    ]
                    for app in self.config.health_checks.applications
                }

            fitness_result.fitness_score = self.evaluator.evaluate(
                start_time=start_time, end_time=end_time, context=context
            )

            # Populate detailed scores breakdown
            if hasattr(self.evaluator, "last_scores") and isinstance(
                self.evaluator.last_scores, list
            ):
                for idx, entry in enumerate(self.evaluator.last_scores):
                    fitness_result.scores.append(
                        FitnessScoreResult(
                            id=idx,
                            fitness_score=entry["score"],
                            weighted_score=entry["weighted_score"],
                        )
                    )
                    # Legacy support for specific health check fields
                    if entry["name"] == "health_check_failure":
                        fitness_result.health_check_failure_score = entry["score"]
                    elif entry["name"] == "health_check_response_time":
                        fitness_result.health_check_response_time_score = entry["score"]

            # Include krkn hub run failure info (legacy support)
            if self.config.fitness_function.include_krkn_failure and returncode == 2:
                fitness_result.krkn_failure_score = KRKN_HUB_FAILURE_SCORE
                fitness_result.fitness_score += KRKN_HUB_FAILURE_SCORE

            logger.info("Total Fitness score: %s", fitness_result.fitness_score)

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
        with tempfile.NamedTemporaryFile(
            suffix=".json",
            dir=graph_json_directory,
            delete=False,
            mode="w",
            encoding="utf-8",
        ) as f:
            json_file = f.name
            json.dump(scenario_json, f, ensure_ascii=False, indent=4)
        logger.info("Created scenario json in path: %s", json_file)

        # Run Json graph
        command = KRKNCTL_GRAPH_RUN_TEMPLATE.format(
            path=json_file,
            kubeconfig=self.config.kubeconfig_file_path,
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
            "name": scenario.krknctl_name,
            "env": env,
        }
        if depends_on is not None:
            result["depends_on"] = depends_on
        return result

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
