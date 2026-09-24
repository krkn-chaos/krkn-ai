"""
JSON Summary Reporter for generating unified results.json files.
"""

import json
import os
import datetime
from typing import Any, Dict, List, Optional

from krkn_ai.models.app import CommandRunResult
from krkn_ai.models.config import ConfigFile, GeneticAlgorithmConfig
from krkn_ai.utils.logger import get_logger
from krkn_ai.constants import STATUS_COMPLETED

logger = get_logger(__name__)


class JSONSummaryReporter:
    """
    Reporter class for generating and saving unified JSON summary files.

    This class consolidates all run statistics into a single results.json file
    for easier analysis and programmatic access.
    """

    def __init__(
        self,
        run_uuid: str,
        config: ConfigFile,
        algo_config: GeneticAlgorithmConfig,
        seen_population: Dict[Any, CommandRunResult],
        best_of_generation: List[CommandRunResult],
        baseline_result: Optional[CommandRunResult] = None,
        all_evaluations: Optional[List[CommandRunResult]] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        completed_generations: int = 0,
        seed: Optional[int] = None,
        scenario_mutation_rate: Optional[float] = None,
    ):
        self.run_uuid = run_uuid
        self.config = config
        self.algo_config = algo_config
        self.seen_population = seen_population
        self.best_of_generation = best_of_generation
        self.baseline_result = baseline_result
        self.all_evaluations = all_evaluations
        self.start_time = start_time
        self.end_time = end_time
        self.completed_generations = completed_generations
        self.seed = seed
        self.scenario_mutation_rate = (
            algo_config.scenario_mutation_rate
            if scenario_mutation_rate is None
            else scenario_mutation_rate
        )
        self.status = STATUS_COMPLETED

    def generate_summary(self) -> Dict[str, Any]:
        """
        Generate a unified results summary containing all run statistics.

        Returns:
            Dict containing run metadata, config summary, best scenarios,
            and fitness progression over generations.
        """
        # Calculate duration
        duration_seconds = 0.0
        if self.start_time and self.end_time:
            duration_seconds = (self.end_time - self.start_time).total_seconds()

        # Get all fitness scores for statistics
        all_fitness_scores = [
            result.fitness_result.fitness_score
            for result in self.seen_population.values()
        ]

        # Calculate average fitness score
        average_fitness_score = 0.0
        if all_fitness_scores:
            average_fitness_score = sum(all_fitness_scores) / len(all_fitness_scores)

        # Get best fitness score
        best_fitness_score = 0.0
        if all_fitness_scores:
            best_fitness_score = max(all_fitness_scores)

        # Count unique scenarios by their string representation
        unique_scenarios = set()
        for result in self.seen_population.values():
            unique_scenarios.add(str(result.scenario))

        # Generate fitness progression from best_of_generation
        fitness_progression = self._build_fitness_progression()

        # Generate best scenarios list (sorted by fitness score, top 10)
        best_scenarios = self._build_best_scenarios()

        # Build the results summary
        results_summary: Dict[str, Any] = {
            "run_id": self.run_uuid,
            "seed": self.seed,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": round(duration_seconds, 2),
            "status": self.status,
            "config": {
                "algorithm_type": self.config.algorithm.value,
                "generations": self.algo_config.generations,
                "population_size": self.algo_config.population_size,
                "mutation_rate": self.algo_config.mutation_rate,
                "scenario_mutation_rate": self.scenario_mutation_rate,
                "crossover_rate": self.algo_config.crossover_rate,
                "composition_rate": self.algo_config.composition_rate,
            },
            "summary": {
                "total_scenarios_executed": len(self.seen_population),
                "unique_scenarios": len(unique_scenarios),
                "generations_completed": self.completed_generations,
                "best_fitness_score": round(best_fitness_score, 4),
                "average_fitness_score": round(average_fitness_score, 4),
            },
            "best_scenarios": best_scenarios,
            "fitness_progression": fitness_progression,
            "population_lineage": self._build_population_lineage(),
        }

        if self.baseline_result is not None:
            results_summary["baseline"] = {
                "fitness_score": self.baseline_result.fitness_result.fitness_score,
                "duration_seconds": self.baseline_result.duration_seconds,
            }

        return results_summary

    def _build_fitness_progression(self) -> List[Dict[str, Any]]:
        """Build fitness progression data from best_of_generation."""
        fitness_progression = []
        for i, result in enumerate(self.best_of_generation):
            # Calculate average fitness for this generation from seen_population
            gen_fitness_scores = [
                r.fitness_result.fitness_score
                for r in self.seen_population.values()
                if r.generation_id == i
            ]
            gen_average = 0.0
            if gen_fitness_scores:
                gen_average = sum(gen_fitness_scores) / len(gen_fitness_scores)

            fitness_progression.append(
                {
                    "generation": i,
                    "best": result.fitness_result.fitness_score,
                    "average": round(gen_average, 4),
                }
            )
        return fitness_progression

    def _build_best_scenarios(self) -> List[Dict[str, Any]]:
        """Build ranked list of best scenarios (top 10)."""
        sorted_results = sorted(
            self.seen_population.values(),
            key=lambda x: x.fitness_result.fitness_score,
            reverse=True,
        )
        best_scenarios = []
        for rank, result in enumerate(sorted_results[:10], start=1):
            scenario_params = {}
            if hasattr(result.scenario, "parameters"):
                scenario_params = {
                    param.get_name(): param.get_value()
                    for param in result.scenario.parameters
                }

            best_scenarios.append(
                {
                    "rank": rank,
                    "scenario_id": result.scenario_id,
                    "generation": result.generation_id,
                    "fitness_score": result.fitness_result.fitness_score,
                    "scenario_type": result.scenario.name,
                    "parameters": scenario_params,
                }
            )
        return best_scenarios

    def _build_population_lineage(self) -> List[Dict[str, Any]]:
        """Export UUID-consistent nodes for reconstructing the GA lineage graph."""
        source = self.all_evaluations
        if source is None:
            source = list(self.seen_population.values())

        lineage = []
        emitted_uuids = set()
        for result in source:
            scenario_uuid = getattr(result.scenario, "id", None)
            if scenario_uuid is None or scenario_uuid in emitted_uuids:
                continue
            emitted_uuids.add(scenario_uuid)
            lineage.append(
                {
                    "scenario_id": result.scenario_id,
                    "scenario_uuid": scenario_uuid,
                    "generation": result.generation_id,
                    "fitness_score": result.fitness_result.fitness_score,
                    "parent_uuids": list(
                        getattr(result.scenario, "parent_uuids", []) or []
                    ),
                    "mutation_type": getattr(result.scenario, "mutation_type", None),
                    "mutated_parameters": list(
                        getattr(result.scenario, "mutated_parameters", []) or []
                    ),
                }
            )
        return lineage

    def save(self, output_dir: str):
        """
        Generate and save the results summary to a JSON file.

        Args:
            output_dir: Directory where results.json will be saved.
        """
        summary = self.generate_summary()
        output_path = os.path.join(output_dir, "results.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        logger.info("Results summary saved to %s", output_path)
