"""Parse committed Krkn-AI scenario artifacts for authenticated result APIs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import yaml
from fastapi import HTTPException, status


_RESULT_PATH = re.compile(r"^(?:yaml|json)/generation_(\d+)/[^/]+\.(?:yaml|yml|json)$")


def _bad_artifact() -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "invalid committed artifact")


def _updating() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "artifact_updating")


def _decode_document(path: str, content: bytes) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
        value = json.loads(text) if path.endswith(".json") else yaml.safe_load(text)
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise _bad_artifact() from exc
    if not isinstance(value, dict):
        raise _bad_artifact()
    return value


def _scenario_key(generation: Any, scenario_id: Any) -> str:
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 0
    ):
        raise _bad_artifact()
    if isinstance(scenario_id, bool) or not isinstance(scenario_id, (str, int, float)):
        raise _bad_artifact()
    if isinstance(scenario_id, float) and scenario_id.is_integer():
        scenario_id = int(scenario_id)
    identifier = str(scenario_id)
    if not identifier:
        raise _bad_artifact()
    return f"{generation}:{identifier}"


@dataclass(frozen=True)
class ScenarioArtifact:
    path: str
    checksum: str
    key: str
    value: dict[str, Any]


@dataclass(frozen=True)
class ParsedRunArtifacts:
    progress: dict[str, Any] | None
    final_results: dict[str, Any] | None
    scenarios: dict[str, ScenarioArtifact]


def parse_run_artifacts(
    files: dict[str, tuple[bytes, str]],
) -> ParsedRunArtifacts:
    """Parse already checksum-verified bytes from one copied manifest snapshot."""
    progress: dict[str, Any] | None = None
    final_results: dict[str, Any] | None = None
    scenarios: dict[str, ScenarioArtifact] = {}
    for path, (content, checksum) in files.items():
        if path == "progress.json":
            progress = _decode_document(path, content)
        elif path == "results.json":
            final_results = _decode_document(path, content)
        else:
            match = _RESULT_PATH.fullmatch(path)
            if match is None:
                continue
            value = _decode_document(path, content)
            key = _scenario_key(value.get("generation_id"), value.get("scenario_id"))
            path_generation = int(match.group(1))
            if (
                path_generation != value["generation_id"]
                or key in scenarios
                or not isinstance(value.get("scenario"), dict)
                or not isinstance(value.get("fitness_result"), dict)
            ):
                raise _bad_artifact()
            scenarios[key] = ScenarioArtifact(path, checksum, key, value)

    if progress is not None:
        result_checksums = progress.get("resultChecksums", {})
        finality = progress.get("fitnessFinalByScenario", {})
        if not isinstance(result_checksums, dict) or not isinstance(finality, dict):
            raise _bad_artifact()
        for key, checksum in result_checksums.items():
            scenario = scenarios.get(key)
            if scenario is None or checksum != scenario.checksum:
                raise _updating()
        for key, is_final in finality.items():
            if not isinstance(is_final, bool):
                raise _bad_artifact()
            if key not in result_checksums or key not in scenarios:
                raise _updating()

    return ParsedRunArtifacts(progress, final_results, scenarios)


def scenario_type(scenario: dict[str, Any]) -> str | None:
    value = scenario.get("name")
    return value if isinstance(value, str) else None


def fitness_state(artifacts: ParsedRunArtifacts, key: str, terminal: bool) -> str:
    finality = (artifacts.progress or {}).get("fitnessFinalByScenario", {})
    if key in finality:
        return "final" if finality[key] else "provisional"
    return "final" if terminal else "provisional"


def scenario_index_row(
    artifact: ScenarioArtifact, artifacts: ParsedRunArtifacts, terminal: bool
) -> dict[str, Any]:
    value = artifact.value
    fitness = value["fitness_result"]
    scenario = value["scenario"]
    duration = value.get("duration_seconds")
    if duration is not None and (
        isinstance(duration, bool) or not isinstance(duration, (int, float))
    ):
        raise _bad_artifact()
    outcome = "succeeded" if value.get("returncode") in (0, 2) else "failed"
    return {
        "generation": value["generation_id"],
        "scenarioId": str(value["scenario_id"]),
        "scenarioType": scenario_type(scenario),
        "outcome": outcome,
        "durationSeconds": duration,
        "fitnessScore": fitness.get("fitness_score"),
        "fitnessState": fitness_state(artifacts, artifact.key, terminal),
    }


def _elapsed_seconds(timestamp: Any, start_time: Any) -> float | None:
    if not isinstance(timestamp, str) or not isinstance(start_time, str):
        return None
    try:
        sample = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        if sample.tzinfo is None and start.tzinfo is not None:
            sample = sample.replace(tzinfo=start.tzinfo)
        elif sample.tzinfo is not None and start.tzinfo is None:
            start = start.replace(tzinfo=sample.tzinfo)
        return (sample - start).total_seconds()
    except ValueError:
        return None


def scenario_detail(
    artifact: ScenarioArtifact, artifacts: ParsedRunArtifacts, terminal: bool
) -> dict[str, Any]:
    value = artifact.value
    scenario = value["scenario"]
    fitness = value["fitness_result"]
    raw_health_checks = value.get("health_check_results", {})
    if not isinstance(raw_health_checks, dict):
        raise _bad_artifact()
    health_checks = []
    for url, samples in raw_health_checks.items():
        if not isinstance(samples, list):
            raise _bad_artifact()
        for sample in samples:
            if not isinstance(sample, dict):
                raise _bad_artifact()
            health_checks.append(
                {
                    "application": sample.get("name") or url,
                    "timestamp": sample.get("timestamp"),
                    "elapsedSeconds": _elapsed_seconds(
                        sample.get("timestamp"), value.get("start_time")
                    ),
                    "responseTimeSeconds": sample.get("response_time"),
                    "statusCode": sample.get("status_code"),
                    "success": sample.get("success"),
                    "error": sample.get("error"),
                }
            )
    scores = fitness.get("scores", [])
    if not isinstance(scores, list) or any(
        not isinstance(score, dict) for score in scores
    ):
        raise _bad_artifact()
    parents = scenario.get("parent_ids", [])
    if not isinstance(parents, list):
        raise _bad_artifact()
    log_path = value.get("log")
    if isinstance(log_path, str):
        log_path = f"logs/{log_path.rsplit('/', 1)[-1]}"
    return {
        "generation": value["generation_id"],
        "scenarioId": str(value["scenario_id"]),
        "scenarioType": scenario_type(scenario),
        "parameters": scenario.get("parameters", []),
        "command": value.get("cmd"),
        "origin": scenario.get("origin"),
        "parentIds": parents,
        "durationSeconds": value.get("duration_seconds"),
        "returnCode": value.get("returncode"),
        "fitnessResult": {
            "fitnessScore": fitness.get("fitness_score"),
            "scores": [
                {
                    "id": score.get("id"),
                    "fitnessScore": score.get("fitness_score"),
                    "weightedScore": score.get("weighted_score"),
                    "normalizedScore": score.get("normalized_score"),
                }
                for score in scores
            ],
            "healthCheckFailureScore": fitness.get("health_check_failure_score"),
            "healthCheckResponseTimeScore": fitness.get(
                "health_check_response_time_score"
            ),
            "krknFailureScore": fitness.get("krkn_failure_score"),
        },
        "healthChecks": health_checks,
        "logPath": log_path,
        "fitnessState": fitness_state(artifacts, artifact.key, terminal),
    }
