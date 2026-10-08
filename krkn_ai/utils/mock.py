import os
from enum import Enum
from typing import Dict, List

from krkn_ai.models.config import HealthCheckResult
from krkn_ai.utils.rng import rng


class MockType(str, Enum):
    RUN = "MOCK_RUN"
    FITNESS = "MOCK_FITNESS"
    HEALTH_CHECK = "MOCK_HEALTH_CHECK"
    CLUSTER = "MOCK_CLUSTER"


_GLOBAL_VAR = "MOCK"


def _env_is_truthy(var: str) -> bool:
    return os.getenv(var, "false").lower().strip() in ("yes", "y", "true", "1")


def is_mock_enabled(mock_type: MockType) -> bool:
    return _env_is_truthy(_GLOBAL_VAR) or _env_is_truthy(mock_type.value)


_DRY_RUN_VAR = "KRKN_AI_DRY_RUN"


def enable_dry_run() -> None:
    """Turn on every mock and flag the process as a dry run.

    A dry run exercises the whole pipeline without a cluster, Prometheus or
    chaos execution; callers use is_dry_run() to skip the mock delays and keep
    the mock fitness values off the console.
    """
    os.environ[_GLOBAL_VAR] = "true"
    os.environ[_DRY_RUN_VAR] = "true"


def is_dry_run() -> bool:
    return _env_is_truthy(_DRY_RUN_VAR)


def generate_mock_health_check_results(
    health_check_config, sample_count: int = 5
) -> Dict[str, List]:
    results: Dict[str, List] = {}
    for app in health_check_config.applications:
        samples = []
        for _ in range(sample_count):
            success = rng.random() > 0.1
            samples.append(
                HealthCheckResult(
                    name=app.name,
                    status_code=app.status_code if success else 503,
                    success=success,
                    response_time=rng.uniform(0.01, 0.5) if success else -1,
                    error=None if success else "mock: service unavailable",
                )
            )
        results[str(app.url)] = samples
    return results
