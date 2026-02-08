"""
Data Aggregator for Krkn-AI Dashboard

Aggregates and transforms Krkn-AI experiment outputs for visualization.
"""

import os
import json
import csv
import yaml
from typing import Dict, List, Any, Optional
from pathlib import Path
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class DataAggregator:
    """Aggregates Krkn-AI experiment data for dashboard visualization."""

    def __init__(self, results_dir: str):
        """
        Initialize DataAggregator.

        Args:
            results_dir: Path to Krkn-AI results directory
        """
        self.results_dir = Path(results_dir)
        self.data: Dict[str, Any] = {}

    def aggregate_all(self) -> Dict[str, Any]:
        """
        Aggregate all data from results directory.

        Returns:
            Dictionary containing all aggregated data
        """
        logger.info("Aggregating data from %s", self.results_dir)

        self.data = {
            "metadata": self._load_metadata(),
            "fitness_scores": self._aggregate_fitness_scores(),
            "health_checks": self._aggregate_health_checks(),
            "scenarios": self._aggregate_scenarios(),
            "best_scenarios": self._load_best_scenarios(),
            "statistics": {},
        }

        # Calculate statistics
        self.data["statistics"] = self._calculate_statistics()

        logger.info("Data aggregation complete")
        return self.data

    def _load_metadata(self) -> Dict[str, Any]:
        """Load experiment metadata from config file."""
        config_path = self.results_dir / "krkn-ai.yaml"
        if not config_path.exists():
            logger.warning("Config file not found: %s", config_path)
            return {}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return {
                    "generations": config.get("generations", 0),
                    "population_size": config.get("population_size", 0),
                    # kubeconfig removed for security (don't leak local paths)
                    "fitness_function": config.get("fitness_function", {}),
                    "scenarios": config.get("scenario", {}),
                }
        except Exception as e:
            logger.error("Error loading config: %s", e)
            return {}

    def _aggregate_fitness_scores(self) -> List[Dict[str, Any]]:
        """Aggregate fitness scores across all generations."""
        fitness_data = []
        seen_scenarios = set()  # Track (gen, scenario_id) to avoid double counting

        # Look for scenario files in yaml/ or json/ directories
        for format_dir in ["yaml", "json"]:
            format_path = self.results_dir / format_dir
            if not format_path.exists():
                continue

            # Iterate through generation directories
            for gen_dir in sorted(format_path.glob("generation_*")):
                try:
                    # Robust parsing of generation ID
                    gen_part = gen_dir.name.split("_")[1]
                    generation_id = int(''.join(filter(str.isdigit, gen_part)))
                except (IndexError, ValueError):
                    logger.error("Could not parse generation ID from %s", gen_dir.name)
                    continue

                # Process each scenario file
                for scenario_file in gen_dir.glob(f"scenario_*.{format_dir}"):
                    try:
                        data = self._load_scenario_file(scenario_file)
                        if data and "fitness_result" in data:
                            scenario_id = data.get("scenario_id", "")
                            
                            # Avoid double counting (YAML + JSON)
                            if (generation_id, scenario_id) in seen_scenarios:
                                continue
                            
                            fitness_data.append({
                                "generation": generation_id,
                                "scenario_id": scenario_id,
                                "scenario_name": data.get("scenario", {}).get("name", ""),
                                "fitness_score": data["fitness_result"].get("fitness_score", 0),
                                "krkn_success": data["fitness_result"].get("krkn_success", True),
                                "start_time": data.get("start_time", ""),
                                "end_time": data.get("end_time", ""),
                            })
                            seen_scenarios.add((generation_id, scenario_id))
                    except Exception as e:
                        logger.error("Error processing %s: %s", scenario_file, e)

        return sorted(fitness_data, key=lambda x: (x["generation"], x["scenario_id"]))

    def _aggregate_health_checks(self) -> List[Dict[str, Any]]:
        """Aggregate health check data from CSV report."""
        health_check_file = self.results_dir / "reports" / "health_check_report.csv"
        if not health_check_file.exists():
            logger.warning("Health check report not found: %s", health_check_file)
            return []

        health_data = []
        try:
            with open(health_check_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Match schema from health_check_reporter.py:
                    # scenario_id, component_name, min_response_time, max_response_time, 
                    # average_response_time, success_count, failure_count
                    
                    try:
                        success_count = int(row.get("success_count", 0))
                        failure_count = int(row.get("failure_count", 0))
                        total = success_count + failure_count
                        
                        health_data.append({
                            "scenario_id": row.get("scenario_id", ""),
                            "application": row.get("component_name", ""),
                            "response_time": float(row.get("average_response_time", 0)),
                            "success_count": success_count,
                            "failure_count": failure_count,
                            "success": failure_count == 0,
                            "success_rate": (success_count / total * 100) if total > 0 else 0
                        })
                    except (ValueError, TypeError) as e:
                        logger.error("Error parsing health check row: %s", e)
        except Exception as e:
            logger.error("Error loading health check data: %s", e)

        return health_data

    def _aggregate_scenarios(self) -> List[Dict[str, Any]]:
        """Aggregate detailed scenario information."""
        scenarios = []

        for format_dir in ["yaml", "json"]:
            format_path = self.results_dir / format_dir
            if not format_path.exists():
                continue

            for gen_dir in sorted(format_path.glob("generation_*")):
                for scenario_file in gen_dir.glob(f"scenario_*.{format_dir}"):
                    try:
                        data = self._load_scenario_file(scenario_file)
                        if data:
                            scenarios.append(data)
                    except Exception as e:
                        logger.debug("Error loading scenario %s: %s", scenario_file, e)

        return scenarios

    def _load_best_scenarios(self) -> List[Dict[str, Any]]:
        """Load best scenarios summary."""
        best_file = self.results_dir / "reports" / "best_scenarios.json"
        if not best_file.exists():
            # Fallback to root for backward compatibility
            best_file = self.results_dir / "best_scenarios.json"
            
        if not best_file.exists():
            logger.warning("Best scenarios file not found in results or reports/")
            return []

        try:
            with open(best_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error loading best scenarios: %s", e)
            return []

    def _load_scenario_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Load a scenario file (JSON or YAML)."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                if file_path.suffix == ".json":
                    return json.load(f)
                elif file_path.suffix == ".yaml":
                    return yaml.safe_load(f)
        except Exception as e:
            logger.debug("Error loading %s: %s", file_path, e)
        return None

    def _calculate_statistics(self) -> Dict[str, Any]:
        """Calculate summary statistics."""
        fitness_scores = self.data.get("fitness_scores", [])
        health_checks = self.data.get("health_checks", [])

        if not fitness_scores:
            return {}

        scores = [s["fitness_score"] for s in fitness_scores]
        successful_runs = sum(1 for s in fitness_scores if s["krkn_success"])

        # Calculate per-generation statistics
        generations = {}
        for score_data in fitness_scores:
            gen = score_data["generation"]
            if gen not in generations:
                generations[gen] = []
            generations[gen].append(score_data["fitness_score"])

        gen_stats = []
        for gen, gen_scores in sorted(generations.items()):
            gen_stats.append({
                "generation": gen,
                "best": max(gen_scores),
                "average": sum(gen_scores) / len(gen_scores),
                "worst": min(gen_scores),
                "count": len(gen_scores),
            })

        # Health check statistics
        health_success_rate = 0
        avg_response_time = 0
        if health_checks:
            successful_checks = sum(1 for h in health_checks if h["success"])
            health_success_rate = (successful_checks / len(health_checks)) * 100
            avg_response_time = sum(h["response_time"] for h in health_checks) / len(health_checks)

        return {
            "total_scenarios": len(fitness_scores),
            "total_generations": len(generations),
            "best_fitness": max(scores) if scores else 0,
            "average_fitness": sum(scores) / len(scores) if scores else 0,
            "worst_fitness": min(scores) if scores else 0,
            "success_rate": (successful_runs / len(fitness_scores)) * 100 if fitness_scores else 0,
            "generation_stats": gen_stats,
            "health_check_success_rate": health_success_rate,
            "average_response_time": avg_response_time,
        }
