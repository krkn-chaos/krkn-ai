"""Parse committed Krkn-AI scenario artifacts for authenticated result APIs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import yaml
from fastapi import HTTPException, status

_SCENARIO_ORIGIN_TAG = (
    "tag:yaml.org,2002:python/object/apply:krkn_ai.models.scenario.base.ScenarioOrigin"
)
_SCENARIO_ORIGINS = {
    "initial",
    "crossover",
    "composition",
    "parameter_mutation",
    "type_mutation",
}


class _ArtifactSafeLoader(yaml.SafeLoader):
    pass


def _construct_legacy_scenario_origin(loader, node):
    values = loader.construct_sequence(node, deep=True)
    if (
        len(values) != 1
        or type(values[0]) is not str
        or values[0] not in _SCENARIO_ORIGINS
    ):
        raise yaml.constructor.ConstructorError(
            None, None, "invalid legacy ScenarioOrigin value", node.start_mark
        )
    return values[0]


_ArtifactSafeLoader.add_constructor(
    _SCENARIO_ORIGIN_TAG, _construct_legacy_scenario_origin
)


_RESULT_PATH = re.compile(r"^(?:yaml|json)/generation_(\d+)/[^/]+\.(?:yaml|yml|json)$")


def _bad_artifact() -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "invalid committed artifact")


def _updating() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "artifact_updating")


def _decode_document(path: str, content: bytes) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
        value = (
            json.loads(text)
            if path.endswith(".json")
            else yaml.load(text, Loader=_ArtifactSafeLoader)
        )
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
        or isinstance(scenario_id, bool)
        or not isinstance(scenario_id, (str, int))
    ):
        raise _bad_artifact()
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

    if scenarios and progress is None:
        raise _updating()
    if progress is not None:
        result_checksums = progress.get("resultChecksums")
        finality = progress.get("fitnessFinalByScenario")
        if not isinstance(result_checksums, dict) or not isinstance(finality, dict):
            raise _bad_artifact()
        for key, checksum in result_checksums.items():
            if (
                not isinstance(key, str)
                or not re.fullmatch(r"\d+:.+", key)
                or not isinstance(checksum, str)
                or not re.fullmatch(r"[0-9a-f]{64}", checksum)
            ):
                raise _bad_artifact()
            scenario = scenarios.get(key)
            if scenario is None or checksum != scenario.checksum:
                raise _updating()
        if any(key not in result_checksums for key in scenarios):
            raise _updating()
        for key, is_final in finality.items():
            if not isinstance(key, str) or not isinstance(is_final, bool):
                raise _bad_artifact()
            if key not in result_checksums or key not in scenarios:
                raise _updating()

    return ParsedRunArtifacts(progress, final_results, scenarios)


def scenario_type(scenario: dict[str, Any]) -> str | None:
    value = scenario.get("name")
    return value if isinstance(value, str) else None


def completed_generation_count(artifacts: ParsedRunArtifacts, terminal: bool) -> int:
    count = None
    if terminal and artifacts.final_results is not None:
        summary = artifacts.final_results.get("summary") or {}
        if not isinstance(summary, dict):
            raise _bad_artifact()
        count = summary.get("generations_completed")
    if count is None:
        count = (artifacts.progress or {}).get("completedGenerations")
    if count is None:
        return 0
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise _bad_artifact()
    return count


def _generation_is_final(artifacts: ParsedRunArtifacts, generation: int) -> bool:
    rows = [
        artifact
        for artifact in artifacts.scenarios.values()
        if artifact.value["generation_id"] == generation
    ]
    finality = (artifacts.progress or {}).get("fitnessFinalByScenario", {})
    return bool(rows) and all(finality.get(row.key) is True for row in rows)


def _fitness_is_final(artifacts: ParsedRunArtifacts, key: str, terminal: bool) -> bool:
    scenario = artifacts.scenarios[key]
    generation = scenario.value["generation_id"]
    return generation < completed_generation_count(
        artifacts, terminal
    ) and _generation_is_final(artifacts, generation)


def fitness_state(artifacts: ParsedRunArtifacts, key: str, terminal: bool) -> str:
    if _fitness_is_final(artifacts, key, terminal):
        return "final"
    return "unfinalized" if terminal else "provisional"


def _optional_number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad_artifact()
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _bad_artifact()
    return value


def _completed_fitness(artifacts: ParsedRunArtifacts, terminal: bool):
    count = completed_generation_count(artifacts, terminal)
    by_generation: dict[int, list[float]] = {}
    incomplete_generations: set[int] = set()
    baseline = None
    for key, artifact in artifacts.scenarios.items():
        if not _fitness_is_final(artifacts, key, terminal):
            continue
        generation = artifact.value["generation_id"]
        fitness = _optional_number(
            artifact.value["fitness_result"].get("fitness_score")
        )
        if artifact.value["scenario_id"] == "baseline":
            if generation == 0:
                baseline = fitness
            continue
        if fitness is None:
            incomplete_generations.add(generation)
        else:
            by_generation.setdefault(generation, []).append(fitness)
    for generation in incomplete_generations:
        by_generation.pop(generation, None)
    progression = [
        {
            "generation": generation,
            "best": max(scores),
            "average": sum(scores) / len(scores),
        }
        for generation, scores in sorted(by_generation.items())
        if generation < count and scores
    ]
    all_scores = [score for values in by_generation.values() for score in values]
    return {
        "bestFitness": max(all_scores) if all_scores else None,
        "averageFitness": sum(all_scores) / len(all_scores) if all_scores else None,
        "baselineFitness": baseline if count > 0 else None,
        "fitnessProgression": progression,
    }


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
    finalized = _fitness_is_final(artifacts, artifact.key, terminal)
    return {
        "generation": value["generation_id"],
        "scenarioId": str(value["scenario_id"]),
        "scenarioType": scenario_type(scenario),
        "outcome": outcome,
        "durationSeconds": duration,
        "fitnessScore": (
            _optional_number(fitness.get("fitness_score")) if finalized else None
        ),
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


def _final_scenario_parameters(
    final_results: dict[str, Any] | None, scenario_key: str
) -> list[dict[str, Any]]:
    if final_results is None:
        return []
    best_scenarios = final_results.get("best_scenarios", [])
    if not isinstance(best_scenarios, list):
        raise _bad_artifact()
    for best in best_scenarios:
        if not isinstance(best, dict):
            raise _bad_artifact()
        key = _scenario_key(best.get("generation"), best.get("scenario_id"))
        parameters = best.get("parameters", {})
        if not isinstance(parameters, dict) or any(
            not isinstance(name, str) for name in parameters
        ):
            raise _bad_artifact()
        if key == scenario_key:
            return [
                {"name": name, "value": value} for name, value in parameters.items()
            ]
    return []


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
    parameters = scenario.get("parameters")
    if parameters is not None and not isinstance(parameters, list):
        raise _bad_artifact()
    if not parameters:
        parameters = _final_scenario_parameters(artifacts.final_results, artifact.key)
    return {
        "generation": value["generation_id"],
        "scenarioId": str(value["scenario_id"]),
        "scenarioType": scenario_type(scenario),
        "parameters": parameters,
        "command": value.get("cmd"),
        "origin": scenario.get("origin"),
        "parentIds": parents,
        "durationSeconds": value.get("duration_seconds"),
        "returnCode": value.get("returncode"),
        "fitnessResult": {
            "fitnessScore": (
                _optional_number(fitness.get("fitness_score"))
                if _fitness_is_final(artifacts, artifact.key, terminal)
                else None
            ),
            "scores": [
                {
                    "id": score.get("id"),
                    "rawScore": _optional_number(score.get("fitness_score")),
                    "normalizedScore": (
                        _optional_number(score.get("normalized_score"))
                        if _fitness_is_final(artifacts, artifact.key, terminal)
                        else None
                    ),
                    "query": _optional_string(score.get("query")),
                    "queryType": _optional_string(score.get("query_type")),
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
