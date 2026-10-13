import datetime
import hashlib
import json
import os
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
from krkn_ai.utils.atomic import atomic_write_bytes, atomic_write_text
from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.output import format_result_filename
from krkn_ai.utils.rng import rng
from krkn_ai.chaos_engines.health_check_watcher import compute_baseline_response_stats


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

        self.current_generation: Optional[int] = None
        self.completed_generations = 0
        self._fitness_progression: list[dict[str, float | int]] = []
        self._partial_scenario_results: dict[str, CommandRunResult] = {}
        self._progress_checksums: dict[str, str] = {}
        self._fitness_finality: dict[str, bool] = {}
        self._score_query_metadata: dict[str, dict[str, dict[str, str | None]]] = {}

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

        self.baseline_result = self.krkn_client.run(
            baseline_scenario, 0, scenario_id="baseline"
        )

        if self.config.fitness_function.include_health_check_response_time:
            stats = compute_baseline_response_stats(
                self.baseline_result.health_check_results
            )
            self.krkn_client.set_baseline_response_stats(stats)
            logger.info("Baseline response stats computed for %d URLs", len(stats))

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
        atomic_write_text(log_save_path, command_result.log)
        return log_save_path

    def set_current_generation(self, generation: int) -> None:
        self.current_generation = generation
        self._write_progress()

    def complete_generation(self, generation: int, results: list) -> None:
        scores = [
            result.fitness_result.fitness_score
            for result in results
            if result.scenario_id != "baseline"
        ]
        self.completed_generations = max(self.completed_generations, generation + 1)
        for result in results:
            key = f"{generation}:{result.scenario_id}"
            if key in self._fitness_finality:
                self._fitness_finality[key] = True
        if generation == 0 and "0:baseline" in self._fitness_finality:
            self._fitness_finality["0:baseline"] = True
        if scores:
            entry = {
                "generation": generation,
                "best": max(scores),
                "average": sum(scores) / len(scores),
            }
            self._fitness_progression = [
                item
                for item in self._fitness_progression
                if item["generation"] != generation
            ]
            self._fitness_progression.append(entry)
            self._fitness_progression.sort(key=lambda item: item["generation"])
        self.current_generation = None
        self._write_progress()

    def update_scenario_results(self, results: list) -> None:
        """Publish updated result artifacts before finalizing their generation."""
        for result in results:
            self._write_scenario_result(result, write_progress=False)
        self._write_progress()

    def save_scenario_result(self, fitness_result: CommandRunResult):
        self._write_scenario_result(fitness_result, write_progress=True)

    def _write_scenario_result(
        self,
        fitness_result: CommandRunResult,
        *,
        write_progress: bool,
    ) -> None:
        logger.debug(
            "Saving scenario result for scenario %s", fitness_result.scenario_id
        )
        result = fitness_result.model_dump(mode="json")
        result["scenario"]["name"] = fitness_result.scenario.name
        parameters = getattr(fitness_result.scenario, "parameters", None)
        if parameters is not None:
            result["scenario"]["parameters"] = [
                {
                    "name": parameter.get_name(),
                    "value": parameter.model_dump(mode="json")["value"],
                }
                for parameter in parameters
            ]
        generation_id = result["generation_id"]
        scenario_id = str(result["scenario_id"])
        result["job_id"] = fitness_result.scenario_id

        log_path = self.save_log_file(fitness_result)
        result["log"] = log_path
        # JSON-mode serialization turns nested enums and timestamps into plain values,
        # so the YAML writer never emits Python-specific object tags.

        output_dir = os.path.join(
            self.output_dir, self.format, "generation_%s" % generation_id
        )
        os.makedirs(output_dir, exist_ok=True)
        filename = format_result_filename(
            self.config.output.result_name_fmt, fitness_result
        )
        if not filename.endswith(f".{self.format}"):
            filename = f"{os.path.splitext(filename)[0]}.{self.format}"
        destination = os.path.join(output_dir, filename)
        key = f"{generation_id}:{scenario_id}"
        if key not in self._score_query_metadata:
            configured_items = {
                str(item.id): {
                    "query": item.query,
                    "query_type": item.type.value,
                }
                for item in self.config.fitness_function.items
            }
            self._score_query_metadata[key] = {
                str(score["id"]): configured_items.get(
                    str(score.get("id")), {"query": None, "query_type": None}
                )
                for score in result["fitness_result"]["scores"]
            }
        for score in result["fitness_result"]["scores"]:
            metadata = self._score_query_metadata[key].get(str(score["id"]), {})
            score["query"] = metadata.get("query")
            score["query_type"] = metadata.get("query_type")

        if self.format == "json":
            content = json.dumps(result, indent=4).encode("utf-8")
        elif self.format == "yaml":
            content = yaml.dump(result, sort_keys=False, width=float("inf")).encode(
                "utf-8"
            )
        else:
            raise ValueError(f"Unsupported result format: {self.format}")
        atomic_write_bytes(destination, content)

        self._partial_scenario_results[key] = fitness_result
        self._progress_checksums[key] = hashlib.sha256(content).hexdigest()
        self._fitness_finality[key] = self._fitness_finality.get(key, False)
        if write_progress:
            self._write_progress()

    def _write_progress(self) -> None:
        ordinary = [
            result
            for result in self._partial_scenario_results.values()
            if result.scenario_id != "baseline"
        ]
        completed = [
            result
            for result in ordinary
            if result.generation_id < self.completed_generations
            and self._fitness_finality.get(
                f"{result.generation_id}:{result.scenario_id}"
            )
        ]
        scores = [result.fitness_result.fitness_score for result in completed]
        baseline = self._partial_scenario_results.get("0:baseline")
        if self.completed_generations == 0 or not self._fitness_finality.get(
            "0:baseline"
        ):
            baseline = None
        progress = {
            "completedGenerations": self.completed_generations,
            "currentGeneration": self.current_generation,
            "completedScenarios": len(ordinary),
            "configuredGenerations": self.config.genetic.generations,
            "populationSize": self.config.genetic.population_size,
            "bestFitness": max(scores) if scores else None,
            "averageFitness": sum(scores) / len(scores) if scores else None,
            "baselineFitness": (
                baseline.fitness_result.fitness_score if baseline is not None else None
            ),
            "fitnessProgression": self._fitness_progression,
            "fitnessFinalByScenario": self._fitness_finality,
            "resultChecksums": self._progress_checksums,
        }
        atomic_write_text(
            os.path.join(self.output_dir, "progress.json"),
            json.dumps(progress, indent=2),
        )
