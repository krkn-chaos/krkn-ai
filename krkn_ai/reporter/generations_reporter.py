import json
import os
from typing import List

import yaml
import pandas as pd

import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from krkn_ai.models.app import CommandRunResult
from krkn_ai.utils.logger import get_module_logger

logger = get_module_logger(__name__)

class GenerationsReporter:
    def __init__(self, output_dir: str, format: str):
        self.output_dir = output_dir
        self.format = format
        os.makedirs(self.output_dir, exist_ok=True)
    
    def save_best_generation_graph(self, best_generations: List[CommandRunResult]):
        if len(best_generations) == 0:
            logger.debug("No best generations to plot")
            return

        os.makedirs(os.path.join(self.output_dir, "reports", "graphs"), exist_ok=True)
        save_path = os.path.join(self.output_dir, "reports", "graphs", "best_generation.png")
        generation_ids = [result.generation_id for result in best_generations]
        fitness_scores = [result.fitness_result.fitness_score for result in best_generations]

        sns.lineplot(x=generation_ids, y=fitness_scores, marker="o")
        plt.title('Best Generation Fitness Score')
        plt.xlabel('Generation')
        plt.ylabel('Fitness Score')
        
        # Force x-axis to show only integer values
        plt.gca().xaxis.set_major_locator(MaxNLocator(integer=True))
        
        plt.tight_layout()
        plt.savefig(save_path, dpi=300)
        plt.close()
        logger.debug("Best generation graph saved to %s", save_path)


    def save_best_generations(self, best_generations: List[CommandRunResult]):
        output_dir = os.path.join(self.output_dir, "reports")
        os.makedirs(output_dir, exist_ok=True)
        save_path = os.path.join(output_dir, "best_scenarios.%s" % self.format)
        results = []
        with open(
            save_path,
            "w",
            encoding="utf-8"
        ) as f:
            for i in range(len(best_generations)):
                scenario_result = best_generations[i].model_dump()
                del scenario_result['log']
                scenario_result['start_time'] = (scenario_result['start_time']).isoformat()
                scenario_result['end_time'] = (scenario_result['end_time']).isoformat()
                results.append(scenario_result)
            if self.format == 'json':
                json.dump(results, f, indent=4)
            elif self.format == 'yaml':
                yaml.dump(results, f, sort_keys=False)
            logger.debug("Best generation report saved to %s", save_path)
