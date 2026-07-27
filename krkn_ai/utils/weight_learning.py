"""Learn fitness-query weights from a run, favoring queries that vary across scenarios."""

import json
import os
import statistics
from collections import defaultdict
from typing import Dict, List, Optional

from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


import datetime

def _discrimination(values: List[float], baseline_noise: float) -> float:
    """Relative spread of a query's values across scenarios; 0 when flat.
    Normalized by max magnitude and baseline variance (SNR).
    """
    if len(values) < 2:
        return 0.0
    scale = max(abs(v) for v in values)
    if scale == 0:
        return 0.0
    
    # SNR = Scenario Spread / (Baseline Noise + epsilon)
    # Epsilon prevents division by zero for perfectly stable baselines
    noise = baseline_noise if baseline_noise > 0 else 1e-6
    spread = statistics.pstdev(values) / scale
    
    return spread / noise


def learn_weights(scenario_results, fitness_items, prom_client=None) -> Dict[str, float]:
    """Normalized weight per query from per-scenario values; {} if there's no signal."""
    id_to_query = {item.id: item.query for item in fitness_items}
    by_query: Dict[str, List[float]] = defaultdict(list)
    for result in scenario_results:
        fitness = getattr(result, "fitness_result", None)
        if fitness is None:
            continue
        for score in fitness.scores:
            query = id_to_query.get(score.id)
            if query is not None:
                by_query[query].append(score.fitness_score)

    baseline_noise: Dict[str, float] = {}
    if prom_client is not None:
        end_time = datetime.datetime.now()
        start_time = end_time - datetime.timedelta(minutes=5)
        
        for q in by_query.keys():
            # Skip if unresolved placeholders remain to prevent silent failures
            if "$ns" in q:
                logger.warning("Unresolved placeholder in query: %s", q)
                baseline_noise[q] = 0.0
                continue
                
            try:
                # Gauge pre-experiment noise over 5m window
                baseline_query = q.replace("$range$", "5m")
                result = prom_client.process_prom_query_in_range(
                    baseline_query,
                    start_time=start_time,
                    end_time=end_time,
                    granularity=30,
                ) or []
                
                # Extract variance if values exist, otherwise assume 0
                if result and len(result) > 0 and 'values' in result[0]:
                    vals = [float(v[1]) for v in result[0]['values']]
                    if len(vals) > 1:
                        # Normalize baseline pstdev by its own scale to make it dimensionless
                        scale = max(abs(v) for v in vals)
                        if scale > 0:
                            baseline_noise[q] = statistics.pstdev(vals) / scale
                        else:
                            baseline_noise[q] = 0.0
                    else:
                        baseline_noise[q] = 0.0
                else:
                    baseline_noise[q] = 0.0
            except Exception as e:
                logger.debug("Failed to fetch baseline noise for query %s: %s", q, e)
                baseline_noise[q] = 0.0

    scores = {q: _discrimination(v, baseline_noise.get(q, 0.0)) for q, v in by_query.items()}
    total = sum(scores.values())
    if total <= 0:
        return {}
    return {q: round(s / total, 4) for q, s in scores.items()}


def save_learned_weights(weights: Dict[str, float], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2)


def load_learned_weights(path: Optional[str]) -> Dict[str, float]:
    """Load learned weights written by a previous run; {} if the file is missing."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError) as error:
        logger.warning("Could not read learned weights %s: %s", path, error)
        return {}
