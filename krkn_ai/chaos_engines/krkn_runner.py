import json
import datetime
import time
from typing import Optional, Tuple

from krkn_ai.chaos_engines.health_check_watcher import HealthCheckWatcher
from krkn_ai.chaos_engines.providers.registry import ProviderRegistry
from krkn_ai.models.app import (
    CommandRunResult,
    FitnessResult,
    FitnessScoreResult,
    KrknRunnerType,
)
from krkn_ai.models.config import ConfigFile, FitnessFunctionType
from krkn_ai.models.custom_errors import FitnessFunctionCalculationError
from krkn_ai.models.scenario.base import (
    BaseScenario,
)
from krkn_ai.utils import run_shell
from krkn_ai.utils.fs import env_is_truthy
from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.prometheus import create_prometheus_client
from krkn_ai.utils.rng import rng

logger = get_logger(__name__)

KRKN_HUB_FAILURE_SCORE = 5


class KrknRunner:
    """
    Orchestrator for chaos scenario execution and fitness evaluation.
    Delegates actual execution to specialized ChaosProviders.
    """

    def __init__(
        self,
        config: ConfigFile,
        output_dir: str,
        runner_type: KrknRunnerType = None,
    ):
        self.config = config
        self.prom_client = create_prometheus_client(self.config.kubeconfig_file_path)
        self.output_dir = output_dir

        # Select and initialize the provider
        self.provider = self._initialize_provider(runner_type)
        logger.info("Initialized with provider: %s", self.provider.get_name())

    def _initialize_provider(self, runner_type: Optional[KrknRunnerType]):
        # Mapping between legacy KrknRunnerType and new providers
        if runner_type == KrknRunnerType.CLI_RUNNER:
            provider_name = "kraken-cli"
        elif runner_type == KrknRunnerType.HUB_RUNNER:
            provider_name = "kraken-hub"
        elif runner_type == KrknRunnerType.MOCK_RUNNER:
            provider_name = "mock"
        elif runner_type == KrknRunnerType.SHELL_RUNNER:
            provider_name = "shell"
        else:
            # Auto-detect
            provider_name = self._detect_best_provider()

        provider_cls = ProviderRegistry.get_provider_class(provider_name)
        return provider_cls(
            kubeconfig=self.config.kubeconfig_file_path,
            wait_duration=self.config.wait_duration,
        )

    def _detect_best_provider(self) -> str:
        # Check in order of preference
        for name in ["kraken-cli", "kraken-hub"]:
            try:
                ProviderRegistry.get_provider_class(name)
                # Note: This is a bit hacky since we need instances to check availability
                # but we'll use a temporary check.
                if name == "kraken-cli":
                    _, code = run_shell("krknctl --version", do_not_log=True)
                    if code == 0:
                        return name
                if name == "kraken-hub":
                    _, code = run_shell("podman --version", do_not_log=True)
                    if code == 0:
                        return name
            except Exception:
                continue

        raise Exception(
            "No suitable chaos provider detected. Please install krknctl or podman."
        )

    def run(self, scenario: BaseScenario, generation_id: int) -> CommandRunResult:
        logger.info("Running scenario: %s", scenario)

        start_time = datetime.datetime.now()
        mono_start = time.monotonic()

        health_check_watcher = HealthCheckWatcher(
            self.config.health_checks, self.config.parameters
        )

        # Execution logic
        if env_is_truthy("MOCK_RUN"):
            time.sleep(rng.randint(1, 3))
            log, returncode, run_uuid, command = "", 0, None, f"mock {scenario}"
        else:
            try:
                health_check_watcher.run()

                # Delegate to provider
                log, returncode, run_uuid, command = self.provider.run(
                    scenario, generation_id, elastic_config=self.config.elastic
                )

                # Post-process for Kraken-specific telemetry if needed
                if run_uuid is None and "kraken" in self.provider.get_name():
                    returncode, run_uuid = self.__extract_returncode_from_run(
                        log, returncode
                    )

                logger.info("Scenario return code: %d", returncode)
            finally:
                health_check_watcher.stop()

        end_time = datetime.datetime.now()
        duration_seconds = time.monotonic() - mono_start

        # Calculate fitness scores
        fitness_result = self._evaluate_fitness(
            start_time, end_time, returncode, health_check_watcher
        )

        return CommandRunResult(
            generation_id=generation_id,
            scenario=scenario,
            cmd=command,
            log=log,
            returncode=returncode,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration_seconds,
            fitness_result=fitness_result,
            health_check_results=health_check_watcher.get_results(),
            run_uuid=run_uuid,
        )

    def _evaluate_fitness(
        self, start_time, end_time, returncode, health_check_watcher
    ) -> FitnessResult:
        fitness_result = FitnessResult()
        health_check_results = health_check_watcher.get_results()

        # Handle misconfiguration
        if returncode != 0 and returncode != 2:
            logger.warning(
                "Scenario failed with return code %d (misconfiguration).", returncode
            )
            if self.config.fitness_function.include_krkn_failure:
                fitness_result.krkn_failure_score = -1.0
            fitness_result.fitness_score = -1.0
            return fitness_result

        # Calculate scores from Prometheus
        if self.config.fitness_function.query is not None:
            fitness_result.fitness_score = self.calculate_fitness_value(
                start=start_time,
                end=end_time,
                query=self.config.fitness_function.query,
                fitness_type=self.config.fitness_function.type,
            )
        elif len(self.config.fitness_function.items) > 0:
            fitness_result = self.calculate_fitness_score_for_items(
                start=start_time, end=end_time
            )

        # Include failure scores
        if self.config.fitness_function.include_krkn_failure and returncode == 2:
            fitness_result.krkn_failure_score = KRKN_HUB_FAILURE_SCORE

        if self.config.fitness_function.include_health_check_failure:
            fitness_result.health_check_failure_score = (
                health_check_watcher.summarize_success_rate(health_check_results)
            )

        if self.config.fitness_function.include_health_check_response_time:
            fitness_result.health_check_response_time_score = (
                health_check_watcher.summarize_response_time(health_check_results)
            )

        # Sum total
        fitness_result.fitness_score = sum(
            [
                fitness_result.fitness_score,
                fitness_result.krkn_failure_score,
                fitness_result.health_check_failure_score,
                fitness_result.health_check_response_time_score,
            ]
        )

        return fitness_result

    # --- Prometheus / Fitness Calculation Logic (Kept for now) ---

    def calculate_fitness_value(self, start, end, query, fitness_type):
        if env_is_truthy("MOCK_FITNESS"):
            return rng.random()

        retries = 3
        retry_delay = 10
        for retry in range(retries):
            try:
                if fitness_type == FitnessFunctionType.point:
                    return self.calculate_point_fitness(start, end, query)
                elif fitness_type == FitnessFunctionType.range:
                    return self.calculate_range_fitness(start, end, query)
            except Exception as error:
                logger.error(f"Fitness calculation failed: {error}")
                time.sleep(retry_delay)
        raise FitnessFunctionCalculationError(
            f"Fitness calculation failed after {retries} retries"
        )

    def calculate_fitness_score_for_items(self, start, end):
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
            results.append(
                FitnessScoreResult(
                    id=fitness_item.id,
                    fitness_score=raw_score,
                    weighted_score=fitness_value,
                )
            )

        return FitnessResult(fitness_score=overall_score, scores=results)

    def calculate_point_fitness(self, start, end, query):
        v_start = self._query_prometheus_single_point(query, start, "start")
        v_end = self._query_prometheus_single_point(query, end, "end")
        return float(v_end) - float(v_start)

    def _query_prometheus_single_point(self, query, timestamp, context):
        result = self.prom_client.process_prom_query_in_range(
            query, start_time=timestamp, end_time=timestamp, granularity=100
        )
        if not result:
            raise FitnessFunctionCalculationError(f"No data for {query} at {timestamp}")
        for series in result:
            if series.get("values"):
                return series["values"][-1][1]
        raise FitnessFunctionCalculationError(f"No values for {query} at {timestamp}")

    def calculate_range_fitness(self, start, end, query):
        if "$range$" in query:
            mins = max(1, int((end - start).total_seconds() / 60))
            query = query.replace("$range$", f"{mins}m")

        result = self.prom_client.process_prom_query_in_range(
            query, start_time=start, end_time=end, granularity=100
        )
        if not result:
            raise FitnessFunctionCalculationError(f"No data for {query} in range")
        for series in result:
            if series.get("values"):
                return float(series["values"][-1][1])
        raise FitnessFunctionCalculationError(f"No values for {query} in range")

    def __extract_returncode_from_run(
        self, log: str, default_returncode: int
    ) -> Tuple[int, Optional[str]]:
        try:
            lines = log.split("\n")
            idx = -1
            for i, line in enumerate(lines):
                if "Chaos data:" in line:
                    idx = i + 1
                    break
            if idx == -1:
                return default_returncode, None

            json_lines = []
            braces = 0
            started = False
            for i in range(idx, len(lines)):
                for char in lines[i]:
                    if char == "{":
                        braces += 1
                        started = True
                    elif char == "}":
                        braces -= 1
                if started:
                    json_lines.append(lines[i])
                if started and braces == 0:
                    break

            if not json_lines:
                return default_returncode, None
            data = json.loads("\n".join(json_lines))
            scenarios = data.get("telemetry", {}).get("scenarios", [])
            if scenarios:
                return scenarios[0].get("exit_status", default_returncode), data.get(
                    "telemetry", {}
                ).get("run_uuid")
            return default_returncode, None
        except Exception as e:
            logger.error("Telemetry extraction failed: %s", e)
            return default_returncode, None
