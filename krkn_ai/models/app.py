import logging
import math
import datetime
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field, field_validator

from krkn_ai.models.scenario.base import BaseScenario
from krkn_ai.models.config import HealthCheckResult
from krkn_ai.utils import id_generator
from krkn_ai.utils.logger import get_logger


logger = get_logger(__name__)
auto_id = id_generator()

# Floor applied to any non-finite (NaN/±Inf) fitness value. PromQL can legitimately
# return NaN/Inf (counter resets, zero denominators, scrape gaps during chaos); left
# unguarded these crash roulette selection and corrupt sorted() ranking.
NONFINITE_FITNESS_FLOOR = 0.0


def coerce_finite_fitness(value: float) -> float:
    """Coerce a non-finite fitness value to NONFINITE_FITNESS_FLOOR with a warning."""
    if math.isfinite(value):
        return value
    logger.warning(
        "Non-finite fitness value %r coerced to %s", value, NONFINITE_FITNESS_FLOOR
    )
    return NONFINITE_FITNESS_FLOOR


@dataclass
class AppContext:
    verbose: int = logging.INFO


class FitnessScoreResult(BaseModel):
    id: int
    fitness_score: float
    weighted_score: float

    _finite = field_validator("fitness_score", "weighted_score", mode="after")(
        staticmethod(coerce_finite_fitness)
    )


class FitnessResult(BaseModel):
    # validate_assignment ensures the invariant also holds when fitness_score is
    # reassigned after construction (e.g. the aggregate sum in KrknRunner.run).
    model_config = ConfigDict(validate_assignment=True)

    scores: List[FitnessScoreResult] = Field(default_factory=list)
    health_check_failure_score: float = 0.0  # Health check failure score
    health_check_response_time_score: float = 0.0  # Health check response time score
    krkn_failure_score: float = 0.0  # Krkn failure score
    fitness_score: float = 0.0  # Overall fitness score

    _finite = field_validator(
        "fitness_score",
        "health_check_failure_score",
        "health_check_response_time_score",
        "krkn_failure_score",
        mode="after",
    )(staticmethod(coerce_finite_fitness))


class CommandRunResult(BaseModel):
    generation_id: int  # Which generation was scenario referred
    scenario_id: int = Field(default_factory=lambda: next(auto_id))  # Scenario ID
    scenario: BaseScenario  # scenario details
    cmd: str  # Krkn-Hub command
    log: str  # Log details or path to log file
    returncode: int  # Return code of Krkn-Hub scenario execution
    start_time: datetime.datetime  # Start date timestamp of the test
    end_time: datetime.datetime  # End date timestamp of the test
    duration_seconds: float = 0.0  # Monotonic-clock elapsed seconds for the run
    fitness_result: FitnessResult  # Fitness result measured for scenario.
    health_check_results: Dict[str, List[HealthCheckResult]] = {}
    run_uuid: Optional[str] = (
        None  # Unique identifier generated from krkn engine during scenario execution
    )


class KrknRunnerType(str, Enum):
    HUB_RUNNER = "HUB_RUNNER"
    CLI_RUNNER = "CLI_RUNNER"
