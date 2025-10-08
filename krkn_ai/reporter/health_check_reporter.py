import os
from datetime import datetime
import pandas as pd

import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
from matplotlib.dates import DateFormatter
from matplotlib.ticker import MaxNLocator

from typing import List

from krkn_ai.models.app import CommandRunResult
from krkn_ai.utils.logger import get_module_logger

logger = get_module_logger(__name__)

class HealthCheckReporter:
    def __init__(self, output_dir: str):
        self.output_dir = os.path.join(output_dir, "reports")
        os.makedirs(self.output_dir, exist_ok=True)

    def save_report(self, fitness_results: List[CommandRunResult]):
        logger.debug("Saving health check report")
        results = []

        for fitness_result in fitness_results:
            health_check_results = fitness_result.health_check_results.values()
            scenario_id = fitness_result.scenario_id
            
            for component_results in health_check_results:
                if len(component_results) == 0:
                    break
                component_name = component_results[0].name
                min_response_time = min([result.response_time for result in component_results])
                max_response_time = max([result.response_time for result in component_results])
                average_response_time = sum([result.response_time for result in component_results]) / len(component_results)
                success_count = sum([result.success for result in component_results])
                failure_count = len(component_results) - success_count

                results.append({
                    "scenario_id": scenario_id,
                    "component_name": component_name,
                    "min_response_time": min_response_time,
                    "max_response_time": max_response_time,
                    "average_response_time": average_response_time,
                    "success_count": success_count,
                    "failure_count": failure_count,
                })

        data = pd.DataFrame(results)
        report_path = os.path.join(self.output_dir, "health_check_report.csv")
        data.to_csv(report_path, index=False)
        logger.debug("Health check report saved to %s", report_path)


    def plot_report(self, result: CommandRunResult):
        if len(result.health_check_results) == 0:
            logger.debug("No health check results to plot")
            return

        logger.debug("Plotting health check result")
        output_dir = os.path.join(self.output_dir, "graphs")
        os.makedirs(output_dir, exist_ok=True)
        save_path = os.path.join(output_dir, "scenario_%d.png" % result.scenario_id)

        # Flatten the data
        records = []
        for _, health_check_results in result.health_check_results.items():
            for health_check_result in health_check_results:
                records.append({
                    "application": health_check_result.name,
                    "timestamp": pd.to_datetime(health_check_result.timestamp),
                    "response_time": health_check_result.response_time,
                    "success": 1 if health_check_result.success else 0,
                })
        df = pd.DataFrame(records)
        df = df.sort_values("timestamp")
        
        # Create formatted timestamp strings for display
        df['timestamp_str'] = df['timestamp'].dt.strftime('%M:%S')
        
        # Create larger figure with better proportions
        fig, axes = plt.subplots(2, 1, figsize=(15, 10))
        
        # Set main title for the entire plot
        fig.suptitle(f'Health Check Results - Scenario {result.scenario_id}', fontsize=16, fontweight='bold')
        
        # Plot 1: Line plot for response time
        sns.lineplot(data=df, x="timestamp", y="response_time", hue="application", marker="o", ax=axes[0])
        
        # Format line plot result
        axes[0].xaxis.set_major_locator(MaxNLocator())
        axes[0].xaxis.set_major_formatter(DateFormatter('%M:%S'))
        axes[0].set_title("Response Time per Application Over Time", fontsize=14)
        axes[0].set_xlabel("Time (mm:ss)", fontsize=12)
        axes[0].set_ylabel("Response Time (s)", fontsize=12)
        axes[0].tick_params(axis='x', rotation=45, labelsize=10)
        axes[0].grid(True, alpha=0.3)
        
        # Plot 2: Heatmap for success
        green_white = LinearSegmentedColormap.from_list("green_red", ["red", "green"])
        pivot = df.pivot_table(index="application", columns="timestamp_str", values="success", aggfunc="max", fill_value=1)
        sns.heatmap(pivot, cmap=green_white, cbar=False, ax=axes[1], linewidths=0.3, linecolor='gray', annot=False,
        vmin=0, vmax=1)
        axes[1].set_title("Success per Application Over Time", fontsize=14) 
        # axes[1].set_xlabel("Time (mm:ss)", fontsize=12)
        axes[1].set_ylabel("Application", fontsize=12)
        axes[1].tick_params(axis='x', rotation=45, labelsize=10)
        axes[1].tick_params(axis='y', labelsize=10)
        axes[1].xaxis.set_major_locator(MaxNLocator())

        plt.tight_layout()
        
        plt.savefig(save_path, dpi=300)
        plt.close()

        logger.debug("Health check graph saved to %s", save_path)


    def write_fitness_result(self, fitness_result: CommandRunResult):
        '''
        Write fitness result to a CSV file.
        '''
        report_path = os.path.join(self.output_dir, "all.csv")
        file_exists = os.path.isfile(report_path)

        df = pd.DataFrame([{
            "generation_id": fitness_result.generation_id,
            "scenario_id": fitness_result.scenario_id,
            "scenario": fitness_result.scenario.name,
            "fitness_score": fitness_result.fitness_result.fitness_score,
        }])

        df.to_csv(report_path, mode='a', header=not file_exists, index=False)
        logger.debug("Fitness result updated.")

