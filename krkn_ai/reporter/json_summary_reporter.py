"""
JSON Summary Reporter for generating unified results.json files.
"""

import json
import os
import datetime
from collections import defaultdict
from typing import Any, Dict, List, Optional

from krkn_ai.models.app import CommandRunResult
from krkn_ai.models.config import ConfigFile
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
        seen_population: Dict[Any, CommandRunResult],
        best_of_generation: List[CommandRunResult],
        baseline_result: Optional[CommandRunResult] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        completed_generations: int = 0,
        seed: Optional[int] = None,
        stopping_reason: Optional[str] = None,
    ):
        """
        Initialize the JSON summary reporter.

        Args:
            run_uuid: Unique identifier for this run.
            config: Configuration used for this run.
            seen_population: Map of scenarios to their execution results.
            best_of_generation: List of best results per generation.
            start_time: When the run started.
            end_time: When the run ended.
            completed_generations: Number of generations completed.
            seed: Random seed used for the run (if any).
            stopping_reason: Human-readable reason the algorithm stopped.
        """
        self.run_uuid = run_uuid
        self.config = config
        self.seen_population = seen_population
        self.best_of_generation = best_of_generation
        self.baseline_result = baseline_result
        self.start_time = start_time
        self.end_time = end_time
        self.completed_generations = completed_generations
        self.seed = seed
        self.stopping_reason = stopping_reason
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

        # Get min fitness score
        min_fitness_score = 0.0
        if all_fitness_scores:
            min_fitness_score = min(all_fitness_scores)

        # Count unique scenarios by their string representation
        unique_scenarios = set()
        for result in self.seen_population.values():
            unique_scenarios.add(str(result.scenario))

        # Generate fitness progression from best_of_generation
        fitness_progression = self._build_fitness_progression()

        # Generate best scenarios list (sorted by fitness score, top 10)
        best_scenarios = self._build_best_scenarios()

        # Generate worst scenarios list (sorted by fitness score, bottom 10)
        worst_scenarios = self._build_worst_scenarios()

        # Build the results summary
        results_summary: Dict[str, Any] = {
            "run_id": self.run_uuid,
            "seed": self.seed,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": round(duration_seconds, 2),
            "status": self.status,
            "stopping_reason": self.stopping_reason,
            "config": {
                "generations": self.config.generations,
                "population_size": self.config.population_size,
                "mutation_rate": self.config.mutation_rate,
                "scenario_mutation_rate": self.config.scenario_mutation_rate,
                "crossover_rate": self.config.crossover_rate,
                "composition_rate": self.config.composition_rate,
            },
            "summary": {
                "total_scenarios_executed": len(self.seen_population),
                "unique_scenarios": len(unique_scenarios),
                "generations_completed": self.completed_generations,
                "best_fitness_score": round(best_fitness_score, 4),
                "min_fitness_score": round(min_fitness_score, 4),
                "average_fitness_score": round(average_fitness_score, 4),
            },
            "best_scenarios": best_scenarios,
            "worst_scenarios": worst_scenarios,
            "fitness_progression": fitness_progression,
            "health_check_summary": self._build_health_check_summary(),
            "slo_breakdown": self._build_slo_breakdown(),
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

    def _build_worst_scenarios(self) -> List[Dict[str, Any]]:
        """Build ranked list of worst scenarios (bottom 10)."""
        sorted_results = sorted(
            self.seen_population.values(),
            key=lambda x: x.fitness_result.fitness_score,
        )
        worst_scenarios = []
        for rank, result in enumerate(sorted_results[:10], start=1):
            scenario_params = {}
            if hasattr(result.scenario, "parameters"):
                scenario_params = {
                    param.get_name(): param.get_value()
                    for param in result.scenario.parameters
                }

            worst_scenarios.append(
                {
                    "rank": rank,
                    "scenario_id": result.scenario_id,
                    "generation": result.generation_id,
                    "fitness_score": result.fitness_result.fitness_score,
                    "scenario_type": result.scenario.name,
                    "parameters": scenario_params,
                }
            )
        return worst_scenarios

    def _build_health_check_summary(self) -> Optional[Dict[str, Any]]:
        """Aggregate health check data across all scenarios, per component."""
        component_data: Dict[str, List[Any]] = defaultdict(list)

        for result in self.seen_population.values():
            for component_results in result.health_check_results.values():
                if not component_results:
                    continue
                component_name = component_results[0].name
                component_data[component_name].extend(component_results)

        if not component_data:
            return None

        summary: Dict[str, Any] = {}
        for component_name, checks in component_data.items():
            response_times = [c.response_time for c in checks]
            success_count = sum(1 for c in checks if c.success)
            failure_count = len(checks) - success_count
            total_checks = len(checks)

            summary[component_name] = {
                "min_response_time": round(min(response_times), 4),
                "max_response_time": round(max(response_times), 4),
                "avg_response_time": round(
                    sum(response_times) / len(response_times), 4
                ),
                "total_checks": total_checks,
                "success_count": success_count,
                "failure_count": failure_count,
                "success_rate": round(success_count / total_checks, 4),
            }

        return summary

    def _build_slo_breakdown(self) -> Optional[Dict[str, Any]]:
        """Aggregate per-SLO fitness scores across all scenarios."""
        slo_data: Dict[int, Dict[str, List[float]]] = defaultdict(
            lambda: {"fitness_scores": [], "weighted_scores": []}
        )

        for result in self.seen_population.values():
            for score in result.fitness_result.scores:
                slo_data[score.id]["fitness_scores"].append(score.fitness_score)
                slo_data[score.id]["weighted_scores"].append(score.weighted_score)

        if not slo_data:
            return None

        breakdown: Dict[str, Any] = {}
        for slo_id, data in slo_data.items():
            breakdown[str(slo_id)] = {
                "avg_fitness_score": round(
                    sum(data["fitness_scores"]) / len(data["fitness_scores"]), 4
                ),
                "avg_weighted_score": round(
                    sum(data["weighted_scores"]) / len(data["weighted_scores"]), 4
                ),
            }

        return breakdown

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
