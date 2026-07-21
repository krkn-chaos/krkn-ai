"""Learn fitness-query weights from a run, favoring queries that vary across scenarios."""

import json
import os
import statistics
from collections import defaultdict
from typing import Dict, List, Optional

from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


def _discrimination(values: List[float]) -> float:
    """Relative spread of a query's values across scenarios; 0 when flat.
    Normalized by max magnitude (not mean)
    """
    if len(values) < 2:
        return 0.0
    scale = max(abs(v) for v in values)
    if scale == 0:
        return 0.0
    return statistics.pstdev(values) / scale


def learn_weights(scenario_results, fitness_items) -> Dict[str, float]:
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

    scores = {q: _discrimination(v) for q, v in by_query.items()}
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
