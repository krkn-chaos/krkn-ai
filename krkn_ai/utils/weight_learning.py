"""Learn fitness-query weights from a run, favoring queries that vary across scenarios."""

import json
import os
import statistics
from collections import defaultdict
from typing import Dict, List, Optional

from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


import datetime
from typing import Dict, List, Optional, Tuple

DEFAULT_NOISE_FLOOR = 0.05


def _discrimination(
    scenario_values: List[float],
    baseline_values: Optional[List[float]] = None,
    noise_floor: float = DEFAULT_NOISE_FLOOR,
) -> float:
    """Relative spread of a query's values across scenarios normalized by shared scale and baseline noise (SNR).

    Uses a shared maximum scale across scenario and baseline values, and applies an additive noise
    floor to prevent explosive weights on near-zero baseline variance.
    """
    if len(scenario_values) < 2:
        return 0.0

    b_vals = baseline_values or []
    all_vals = scenario_values + b_vals
    scale = max(abs(v) for v in all_vals)
    if scale == 0:
        return 0.0

    spread = statistics.pstdev(scenario_values) / scale
    noise = (statistics.pstdev(b_vals) / scale) if len(b_vals) > 1 else 0.0

    return spread / (noise + noise_floor)


def learn_weights(
    scenario_results,
    fitness_items,
    prom_client=None,
    baseline_window: Optional[Tuple[datetime.datetime, datetime.datetime]] = None,
) -> Dict[str, float]:
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

    baseline_data: Dict[str, List[float]] = {}
    if prom_client is not None:
        if baseline_window is not None:
            start_time, end_time = baseline_window
        else:
            # Fallback to pre-experiment window using earliest scenario start_time
            scenario_starts = [
                getattr(r, "start_time")
                for r in scenario_results
                if getattr(r, "start_time", None) is not None
            ]
            if scenario_starts:
                end_time = min(scenario_starts)
                start_time = end_time - datetime.timedelta(minutes=5)
            else:
                end_time = datetime.datetime.now(datetime.timezone.utc)
                start_time = end_time - datetime.timedelta(minutes=5)

        for q in by_query.keys():
            # Skip if unresolved placeholders remain to prevent silent failures
            if "$ns" in q:
                logger.warning("Unresolved placeholder in query: %s", q)
                baseline_data[q] = []
                continue

            try:
                # Gauge pre-experiment noise over steady-state baseline window
                baseline_query = q.replace("$range$", "5m")
                result = (
                    prom_client.process_prom_query_in_range(
                        baseline_query,
                        start_time=start_time,
                        end_time=end_time,
                        granularity=30,
                    )
                    or []
                )

                if result and len(result) > 0 and "values" in result[0]:
                    vals = [float(v[1]) for v in result[0]["values"]]
                    baseline_data[q] = vals
                else:
                    baseline_data[q] = []
            except Exception as e:
                logger.debug("Failed to fetch baseline noise for query %s: %s", q, e)
                baseline_data[q] = []

    scores = {
        q: _discrimination(v, baseline_data.get(q)) for q, v in by_query.items()
    }
    total = sum(scores.values())
    if total <= 0:
        return {}
    return {q: round(s / total, 4) for q, s in scores.items()}


def save_learned_weights(weights: Dict[str, float], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2)


def load_learned_weights(path: Optional[str]) -> Dict[str, float]:
    """Load learned weights; {} if the file is missing or not a JSON object."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            weights = json.load(f)
        if not isinstance(weights, dict):
            logger.warning("Learned weights %s must contain a JSON object", path)
            return {}
        return weights
    except (OSError, ValueError) as error:
        logger.warning("Could not read learned weights %s: %s", path, error)
        return {}
