import logging
import datetime
from enum import Enum
from typing import Dict, List
from dataclasses import dataclass
from pydantic import BaseModel, Field

from krkn_ai.models.scenario.base import BaseScenario
from krkn_ai.models.config import HealthCheckResult
from krkn_ai.utils import id_generator


auto_id = id_generator()

@dataclass
class AppContext:
    verbose: int = logging.INFO

class FitnessScoreResult(BaseModel):
    id: int
    fitness_score: float
    weighted_score: float


class FitnessResult(BaseModel):
    scores: List[FitnessScoreResult] = []
    health_check_failure_score: float = 0.0 # Health check failure score
    health_check_response_time_score: float = 0.0 # Health check response time score
    krkn_failure_score: float = 0.0 # Krkn failure score
    fitness_score: float = 0.0    # Overall fitness score



class CommandRunResult(BaseModel):
    generation_id: int      # Which generation was scenario referred
    scenario_id: int = Field(default_factory=lambda: next(auto_id))        # Scenario ID
    scenario: BaseScenario  # scenario details
    cmd: str                # Krkn-Hub command 
    log: str                # Log details or path to log file
    returncode: int         # Return code of Krkn-Hub scenario execution
    start_time: datetime.datetime   # Start date timestamp of the test 
    end_time: datetime.datetime     # End date timestamp of the test
    fitness_result: FitnessResult   # Fitness result measured for scenario.
    health_check_results: Dict[str, List[HealthCheckResult]] = {}


class KrknRunnerType(str, Enum):
    HUB_RUNNER = "HUB_RUNNER"
    CLI_RUNNER = "CLI_RUNNER"
