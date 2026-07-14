import os
import datetime
import json
import uuid
from abc import ABC, abstractmethod
from typing import Dict, Optional

import yaml

from krkn_ai.chaos_engines.krkn_runner import KrknRunner
from krkn_ai.models.app import CommandRunResult, KrknRunnerType
from krkn_ai.models.config import ConfigFile
from krkn_ai.models.scenario.base import BaseScenario
from krkn_ai.models.scenario.factory import ScenarioFactory
from krkn_ai.reporter.health_check_reporter import HealthCheckReporter
from krkn_ai.utils.elastic_client import ElasticSearchClient
from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.output import format_result_filename
from krkn_ai.utils.rng import rng

logger = get_logger(__name__)


class BaseEngine(ABC):
    def __init__(
        self,
        config: ConfigFile,
        output_dir: str,
        format: str,
        runner_type: KrknRunnerType = None,
        run_uuid: Optional[str] = None,
    ):
        self.config = config
        self.format = format
        self.run_uuid = run_uuid if run_uuid is not None else str(uuid.uuid4())
        self.output_dir = output_dir

        rng.set_seed(self.config.seed)
        if self.config.seed is not None:
            logger.info("Random seed: %s (reproducible mode)", self.config.seed)
        else:
            logger.info("Random seed: None (non-reproducible mode)")

        self.krkn_client = KrknRunner(
            config, output_dir=self.output_dir, runner_type=runner_type
        )

        self.valid_scenarios = ScenarioFactory.generate_valid_scenarios(self.config)
        self.seen_population: Dict[BaseScenario, CommandRunResult] = {}

        self.baseline_result: Optional[CommandRunResult] = None

        self.health_check_reporter = HealthCheckReporter(
            self.output_dir, self.config.output
        )

        self.elastic_client: Optional[ElasticSearchClient] = None
        if self.config.elastic is not None:
            self.elastic_client = ElasticSearchClient(self.config.elastic)

        self.start_time: Optional[datetime.datetime] = None
        self.end_time: Optional[datetime.datetime] = None
        self.seed: Optional[int] = self.config.seed

        self.save_config()
        if self.elastic_client is not None:
            self.elastic_client.index_config(self.config, self.run_uuid)

    @abstractmethod
    def optimize(self): ...

    def run_baseline(self):
        if not self.config.baseline.enable:
            logger.info("Baseline is disabled, skipping baseline scenario")
            return

        logger.info(
            "Running baseline scenario for %d seconds", self.config.baseline.duration
        )
        baseline_scenario = ScenarioFactory.create_dummy_scenario()
        baseline_scenario.end.value = self.config.baseline.duration

        self.baseline_result = self.krkn_client.run(baseline_scenario, 0)
        self.baseline_result.scenario_id = "baseline"

        self.save_scenario_result(self.baseline_result)
        self.health_check_reporter.plot_report(self.baseline_result)
        self.health_check_reporter.write_fitness_result(self.baseline_result)
        if self.elastic_client is not None:
            self.elastic_client.index_run_result(self.baseline_result, self.run_uuid)

    def evaluate_scenario(
        self, scenario: BaseScenario, generation_id: int
    ) -> CommandRunResult:
        scenario_result = self.krkn_client.run(scenario, generation_id)
        self.seen_population[scenario] = scenario_result

        self.save_scenario_result(scenario_result)
        self.health_check_reporter.plot_report(scenario_result)
        self.health_check_reporter.write_fitness_result(scenario_result)
        if self.elastic_client is not None:
            self.elastic_client.index_run_result(scenario_result, self.run_uuid)

        return scenario_result

    def save_config(self):
        logger.info("Saving config file to config.yaml")
        output_dir = self.output_dir
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "krkn-ai.yaml"), "w", encoding="utf-8") as f:
            config_data = self.config.model_dump(mode="json")
            config_data["cluster_components"] = (
                self.config.cluster_components.model_dump(
                    mode="json", exclude_defaults=True
                )
            )
            yaml.dump(config_data, f, sort_keys=False)

    def save_log_file(self, command_result: CommandRunResult):
        dir_path = os.path.join(self.output_dir, "logs")
        os.makedirs(dir_path, exist_ok=True)
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

        result["log"] = self.save_log_file(fitness_result)
        result["start_time"] = (result["start_time"]).isoformat()
        result["end_time"] = (result["end_time"]).isoformat()

        output_dir = os.path.join(
            self.output_dir, self.format, "generation_%s" % generation_id
        )
        os.makedirs(output_dir, exist_ok=True)

        filename = format_result_filename(
            self.config.output.result_name_fmt, fitness_result
        )
        if not filename.endswith(f".{self.format}"):
            base_name = os.path.splitext(filename)[0]
            filename = f"{base_name}.{self.format}"

        with open(
            os.path.join(output_dir, filename), "w", encoding="utf-8"
        ) as file_handler:
            if self.format == "json":
                json.dump(result, file_handler, indent=4)
            elif self.format == "yaml":
                yaml.dump(result, file_handler, sort_keys=False)
