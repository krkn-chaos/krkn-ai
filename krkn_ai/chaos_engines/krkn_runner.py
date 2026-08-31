import datetime
import time
from typing import Dict, Optional, Tuple

from krkn_ai.chaos_engines.commands import build_scenario_command, inject_es_config
from krkn_ai.chaos_engines.composite import build_graph_command
from krkn_ai.chaos_engines.fitness import FitnessCalculator
from krkn_ai.chaos_engines.health_check_watcher import HealthCheckWatcher
from krkn_ai.models.app import (
    CommandRunResult,
    FitnessResult,
    KrknRunnerType,
)
from krkn_ai.models.config import ConfigFile
from krkn_ai.models.scenario.base import (
    Scenario,
    BaseScenario,
    CompositeScenario,
)
from krkn_ai.utils import run_shell
from krkn_ai.utils.mock import (
    MockType,
    is_mock_enabled,
    generate_mock_health_check_results,
)
from krkn_ai.utils.logger import get_logger, is_verbose
from krkn_ai.utils.prometheus import create_prometheus_client
from krkn_ai.utils.rng import rng
from krkn_ai.chaos_engines.telemetry_parser import extract_telemetry_from_log
from krkn_ai.chaos_engines.operator_runner import OperatorExecutor

logger = get_logger(__name__)

KRKN_HUB_FAILURE_SCORE = 0.5


class KrknRunner:
    def __init__(
        self,
        config: ConfigFile,
        output_dir: str,
        runner_type: Optional[KrknRunnerType] = None,
    ):
        self.config = config

        if is_mock_enabled(MockType.FITNESS):
            self.prom_client = None
            self.fitness_calculator = FitnessCalculator(None, config.fitness_function)
        else:
            self.prom_client = create_prometheus_client(
                self.config.kubeconfig_file_path
            )
            self.fitness_calculator = FitnessCalculator(
                self.prom_client, config.fitness_function
            )
            logger.info("Running pre-flight fitness function validation...")
            self.fitness_calculator.preflight_check()
            logger.info("Pre-flight fitness validation passed.")

        self._baseline_response_stats: Optional[Dict[str, Tuple[float, float]]] = None

        self.output_dir = output_dir
        if is_mock_enabled(MockType.RUN):
            self.runner_type = runner_type
        elif runner_type is None:
            self.runner_type = self.__check_runner_availability()
        else:
            logger.debug("Using user provided runner type: %s", runner_type)
            self.runner_type = runner_type
        self._operator_executor = (
            OperatorExecutor(self.config)
            if self.runner_type == KrknRunnerType.OPERATOR_RUNNER
            else None
        )

    def __check_runner_availability(self):
        krknctl_available = True
        podman_available = True
        _, returncode = run_shell("krknctl --version", do_not_log=True)
        if returncode != 0:
            krknctl_available = False
            logger.warning("krknctl is not available.")

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

    def set_baseline_response_stats(
        self, stats: Dict[str, Tuple[float, float]]
    ) -> None:
        self._baseline_response_stats = stats

    def run(self, scenario: BaseScenario, generation_id: int) -> CommandRunResult:
        logger.info("Running scenario: %s", scenario)

        start_time = datetime.datetime.now()
        mono_start = time.monotonic()

        log, returncode, run_uuid, resiliency_score = None, None, None, None
        command = ""

        health_check_watcher = HealthCheckWatcher(
            self.config.health_checks, self.config.parameters
        )

        if is_mock_enabled(MockType.RUN):
            time.sleep(rng.randint(1, 3))
            log, returncode = "", 0
        else:
            assert self.runner_type is not None
            if self.runner_type == KrknRunnerType.OPERATOR_RUNNER:
                command = f"operator:{getattr(scenario, 'krknhub_image', '')}"
                assert self._operator_executor is not None
                try:
                    health_check_watcher.run()
                    log, returncode = self._operator_executor.execute(scenario)
                    telemetry = extract_telemetry_from_log(log, returncode)
                    returncode = telemetry.exit_status
                    run_uuid = telemetry.run_uuid
                    resiliency_score = telemetry.resiliency_score
                    logger.info("Krkn scenario return code: %d", returncode)
                finally:
                    health_check_watcher.stop()
            else:
                if isinstance(scenario, CompositeScenario):
                    command = build_graph_command(
                        scenario, self.config.kubeconfig_file_path, self.output_dir
                    )
                elif isinstance(scenario, Scenario):
                    command = build_scenario_command(
                        scenario, self.config, self.runner_type
                    )
                else:
                    raise NotImplementedError("Scenario unable to run")

                try:
                    health_check_watcher.run()

                    log, returncode = run_shell(
                        inject_es_config(command, self.config, self.runner_type, True),
                        do_not_log=not is_verbose(),
                    )

                    if isinstance(scenario, CompositeScenario):
                        pass
                    else:
                        telemetry = extract_telemetry_from_log(log, returncode)
                        returncode = telemetry.exit_status
                        run_uuid = telemetry.run_uuid
                        resiliency_score = telemetry.resiliency_score
                    logger.info("Krkn scenario return code: %d", returncode)

                finally:
                    health_check_watcher.stop()

        end_time = datetime.datetime.now()
        duration_seconds = time.monotonic() - mono_start

        fitness_result: FitnessResult = FitnessResult()

        if is_mock_enabled(MockType.HEALTH_CHECK):
            health_check_results = generate_mock_health_check_results(
                self.config.health_checks
            )
        else:
            health_check_results = health_check_watcher.get_results()

        if returncode != 0 and returncode != 2:
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
            if self.config.fitness_function.query is not None:
                fitness_value = self.fitness_calculator.calculate_fitness_value(
                    start=start_time,
                    end=end_time,
                    query=self.config.fitness_function.query,
                    fitness_type=self.config.fitness_function.type,
                )
                fitness_result.fitness_score = fitness_value
            elif len(self.config.fitness_function.items) > 0:
                fitness_result = (
                    self.fitness_calculator.calculate_fitness_score_for_items(
                        start=start_time, end=end_time
                    )
                )

            if self.config.fitness_function.include_krkn_failure:
                if resiliency_score is not None:
                    fitness_result.krkn_failure_score = (
                        100.0 - resiliency_score
                    ) / 100.0
                elif returncode == 2:
                    fitness_result.krkn_failure_score = KRKN_HUB_FAILURE_SCORE

            if self.config.fitness_function.include_health_check_failure:
                fitness_result.health_check_failure_score = (
                    health_check_watcher.summarize_success_rate(health_check_results)
                )
            if self.config.fitness_function.include_health_check_response_time:
                fitness_result.health_check_response_time_score = (
                    health_check_watcher.summarize_response_time(
                        health_check_results,
                        baseline_stats=self._baseline_response_stats,
                    )
                )

            n = self.config.fitness_function.num_components
            raw_total = sum(
                [
                    fitness_result.fitness_score,
                    fitness_result.krkn_failure_score,
                    fitness_result.health_check_failure_score,
                    fitness_result.health_check_response_time_score,
                ]
            )
            fitness_result.fitness_score = (raw_total / n * 100) if n else 0.0
            slo_total = sum(s.weighted_score for s in fitness_result.scores)
            logger.info(
                "Fitness: %.1f%%  (SLO: %.3f | HC fail: %.3f | HC resp: %.3f | krkn: %.3f)",
                fitness_result.fitness_score,
                slo_total,
                fitness_result.health_check_failure_score,
                fitness_result.health_check_response_time_score,
                fitness_result.krkn_failure_score,
            )
            if fitness_result.scores:
                logger.debug(
                    "SLO breakdown: %s",
                    "  ".join(
                        f"[{s.id}]={s.fitness_score:.4f}" for s in fitness_result.scores
                    ),
                )

        return CommandRunResult(
            generation_id=generation_id,
            scenario=scenario,
            cmd=inject_es_config(command, self.config, self.runner_type, False)
            if self.runner_type is not None
            else "",
            log=log,
            returncode=returncode,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration_seconds,
            fitness_result=fitness_result,
            health_check_results=health_check_results,
            run_uuid=run_uuid,
            resiliency_score=resiliency_score,
        )

    def runner_command(self, scenario: Scenario) -> str:
        assert self.runner_type is not None
        return build_scenario_command(scenario, self.config, self.runner_type)

    def process_es_env_string(self, command: str, enable: bool) -> str:
        assert self.runner_type is not None
        return inject_es_config(command, self.config, self.runner_type, enable)

    def graph_command(self, scenario: CompositeScenario) -> str:
        return build_graph_command(
            scenario, self.config.kubeconfig_file_path, self.output_dir
        )
