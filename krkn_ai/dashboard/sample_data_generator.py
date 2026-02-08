"""
Sample data generator for testing Krkn-AI dashboard.

Creates mock experiment results for dashboard development and testing.
"""

import json
import csv
import yaml
import os
from pathlib import Path
from datetime import datetime, timedelta
import random


def generate_sample_data(output_dir: str = "./sample_results"):
    """
    Generate sample Krkn-AI experiment data for testing.

    Args:
        output_dir: Directory to save sample data
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Create directory structure
    (output_path / "yaml").mkdir(exist_ok=True)
    (output_path / "json").mkdir(exist_ok=True)
    (output_path / "reports").mkdir(exist_ok=True)

    # Generate config
    config = {
        "generations": 10,
        "population_size": 5,
        "kubeconfig_file_path": "/path/to/kubeconfig",
        "fitness_function": {
            "name": "prometheus_metric",
            "metric": "http_requests_total",
            "target": 100,
        },
        "scenario": {
            "pod": {"enabled": True},
            "app_outage": {"enabled": True},
            "network": {"enabled": True},
        },
    }

    with open(output_path / "krkn-ai.yaml", "w") as f:
        yaml.dump(config, f)

    # Generate scenarios and fitness scores
    best_scenarios = []
    health_checks = []
    scenario_types = ["pod_scenario", "app_outage", "network_chaos", "container_kill"]

    start_time = datetime.now() - timedelta(hours=2)

    for gen in range(10):
        gen_dir_yaml = output_path / "yaml" / f"generation_{gen}"
        gen_dir_json = output_path / "json" / f"generation_{gen}"
        gen_dir_yaml.mkdir(exist_ok=True)
        gen_dir_json.mkdir(exist_ok=True)

        gen_best_fitness = 0
        gen_best_scenario = None

        for scenario_idx in range(5):
            scenario_id = f"gen{gen}_scenario{scenario_idx}"
            scenario_type = random.choice(scenario_types)

            # Generate fitness score with upward trend
            base_fitness = 50 + (gen * 3) + random.uniform(-5, 10)
            # Add occasional drops for anomaly detection
            if gen == 5 and scenario_idx == 0:
                base_fitness -= 20  # Intentional drop for anomaly

            fitness_score = min(100, max(0, base_fitness))

            scenario_data = {
                "scenario_id": scenario_id,
                "scenario": {
                    "name": scenario_type,
                    "namespace": "default",
                    "label_selector": "app=demo",
                },
                "fitness_result": {
                    "fitness_score": fitness_score,
                    "krkn_success": random.random() > 0.1,  # 90% success rate
                },
                "start_time": (start_time + timedelta(minutes=gen * 10 + scenario_idx * 2)).isoformat(),
                "end_time": (start_time + timedelta(minutes=gen * 10 + scenario_idx * 2 + 1)).isoformat(),
            }

            # Save as YAML and JSON
            with open(gen_dir_yaml / f"scenario_{scenario_idx}.yaml", "w") as f:
                yaml.dump(scenario_data, f)

            with open(gen_dir_json / f"scenario_{scenario_idx}.json", "w") as f:
                json.dump(scenario_data, f, indent=2)

            # Track best scenario
            if fitness_score > gen_best_fitness:
                gen_best_fitness = fitness_score
                gen_best_scenario = scenario_data

            # Generate health checks
            for app in ["frontend", "cart", "catalogue"]:
                # Introduce failures for cart service occasionally
                success = True
                response_time = random.uniform(0.1, 0.5)

                if app == "cart" and random.random() < 0.3:  # 30% failure for cart
                    success = False
                    response_time = random.uniform(1.0, 3.0)

                health_checks.append({
                    "scenario_id": scenario_id,
                    "generation": gen,
                    "application": app,
                    "timestamp": (start_time + timedelta(minutes=gen * 10 + scenario_idx * 2)).isoformat(),
                    "response_time": response_time,
                    "status_code": 200 if success else 500,
                    "success": success,
                    "error": "" if success else "Connection timeout",
                })

        if gen_best_scenario:
            best_scenarios.append({
                "generation": gen,
                "scenario": gen_best_scenario["scenario"],
                "fitness_score": gen_best_fitness,
            })

    # Save best scenarios
    with open(output_path / "best_scenarios.json", "w") as f:
        json.dump(best_scenarios, f, indent=2)

    # Save health check report
    with open(output_path / "reports" / "health_check_report.csv", "w", newline="") as f:
        fieldnames = ["scenario_id", "generation", "application", "timestamp", "response_time", "status_code", "success", "error"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(health_checks)

    print(f"Sample data generated in: {output_path}")
    print(f"Total scenarios: {10 * 5}")
    print(f"Total health checks: {len(health_checks)}")
    print(f"\nTo generate dashboard, run:")
    print(f"  krkn_ai dashboard -r {output_path} -o dashboard.html")


if __name__ == "__main__":
    generate_sample_data()
