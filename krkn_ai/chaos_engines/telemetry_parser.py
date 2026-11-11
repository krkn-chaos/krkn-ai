"""
Telemetry extraction from Krkn run logs.

Extracts exit_status, run_uuid, and resiliency_score from the "Chaos data:"
JSON telemetry block emitted by Krkn at the end of a run.

Fallback chain:
  1. JSON decode via raw_decode (handles ANSI codes, trailing garbage)
  2. Regex pattern matching for exit_status / run_uuid / resiliency_score keys
  3. Return caller-supplied default
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

_EXIT_STATUS_RE = re.compile(r'"exit_status"\s*:\s*(-?\d+)')
_RUN_UUID_RE = re.compile(r'"run_uuid"\s*:\s*"([^"]+)"')
_RESILIENCY_SCORE_RE = re.compile(r'"resiliency_score"\s*:\s*(\d+(?:\.\d+)?)')
_TOTAL_SLOS_RE = re.compile(r'"total_slos"\s*:\s*(\d+)')
_OVERALL_REPORT_RE = re.compile(r'"overall_resiliency_report"\s*:\s*\{')

CHAOS_DATA_MARKER = "Chaos data:"


@dataclass
class TelemetryResult:
    exit_status: int
    run_uuid: Optional[str] = None
    resiliency_score: Optional[float] = None
    recovery_failed: bool = False


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _measured_score(score: float, total_slos: Any) -> Optional[float]:
    """
    Return None when krkn evaluated no SLOs.

    krkn always prints overall_resiliency_report; when resiliency is disabled
    (e.g. no Prometheus URL) it keeps the default resiliency_score 0 with
    total_slos 0, which is not a measurement. A missing or non-numeric
    total_slos keeps the score, as before.
    """
    try:
        slo_count = int(total_slos)
    except (TypeError, ValueError):
        return score
    if slo_count == 0:
        return None
    return score


def extract_telemetry_from_log(log: str, default_returncode: int) -> TelemetryResult:
    """
    Extract Krkn return code, run_uuid, and resiliency_score from a run log.

    Fallback chain:
      1. Locate "Chaos data:" marker, strip ANSI, then use JSONDecoder.raw_decode
         to find a valid telemetry JSON object.
      2. If JSON decode fails, use regex to find values directly.
      3. Return default_returncode if nothing is found.

    Returns:
        TelemetryResult with extracted values.
    """
    marker_idx = log.find(CHAOS_DATA_MARKER)
    if marker_idx == -1:
        logger.warning("Could not find '%s' in log", CHAOS_DATA_MARKER)
        return TelemetryResult(exit_status=default_returncode)

    after_marker = log[marker_idx + len(CHAOS_DATA_MARKER) :]

    result = _try_json_extraction(after_marker, default_returncode)
    if result is not None:
        return result

    result = _try_regex_extraction(after_marker)
    if result is not None:
        return result

    logger.warning("No exit_status found in telemetry data")
    return TelemetryResult(exit_status=default_returncode)


def _try_json_extraction(
    text: str, default_returncode: int
) -> Optional[TelemetryResult]:
    """
    Attempt JSON-based extraction using raw_decode after stripping ANSI codes.
    Scans for valid JSON objects and validates the telemetry structure.
    """
    clean_text = strip_ansi(text)
    decoder = json.JSONDecoder()
    search_idx = 0

    while True:
        object_start = clean_text.find("{", search_idx)
        if object_start == -1:
            break

        try:
            obj, object_end = decoder.raw_decode(clean_text[object_start:])
        except (json.JSONDecodeError, ValueError):
            search_idx = object_start + 1
            continue

        search_idx = object_start + object_end

        if not isinstance(obj, dict):
            continue

        telemetry = obj.get("telemetry")
        if not isinstance(telemetry, dict):
            continue

        scenarios = telemetry.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            continue

        first = scenarios[0]
        if not isinstance(first, dict):
            continue

        exit_status = first.get("exit_status", default_returncode)
        run_uuid = telemetry.get("run_uuid", None)

        resiliency_score = None
        report = telemetry.get("overall_resiliency_report")
        if isinstance(report, dict):
            raw = report.get("resiliency_score")
            if raw is not None:
                resiliency_score = _measured_score(float(raw), report.get("total_slos"))

        logger.debug("Extracted exit_status: %s (json)", exit_status)
        logger.debug("Extracted run_uuid: %s (json)", run_uuid)
        logger.debug("Extracted resiliency_score: %s (json)", resiliency_score)
        return TelemetryResult(
            exit_status=exit_status,
            run_uuid=run_uuid,
            resiliency_score=resiliency_score,
            recovery_failed=_has_recovery_failure(first, telemetry),
        )

    return None


def _has_recovery_failure(scenario: dict, telemetry: dict) -> bool:
    if scenario.get("exit_status") not in (1, 2):
        return False
    errors = telemetry.get("error_logs", [])
    if not isinstance(errors, list) or errors:
        return False
    recovery_failed = False
    for key in ("affected_pods", "affected_vmis"):
        snapshot = scenario.get(key)
        if not isinstance(snapshot, dict):
            continue
        if snapshot.get("error") is not None:
            return False
        unrecovered = snapshot.get("unrecovered")
        if (
            isinstance(unrecovered, list)
            and unrecovered
            and all(isinstance(target, dict) and target for target in unrecovered)
        ):
            recovery_failed = True
    return recovery_failed


def _try_regex_extraction(text: str) -> Optional[TelemetryResult]:
    """
    Fallback: use regex to locate exit_status, run_uuid, and resiliency_score
    directly from the raw (or ANSI-contaminated) text.
    """
    clean_text = strip_ansi(text)

    exit_match = _EXIT_STATUS_RE.search(clean_text)
    if not exit_match:
        return None

    exit_status = int(exit_match.group(1))
    uuid_match = _RUN_UUID_RE.search(clean_text)
    run_uuid = uuid_match.group(1) if uuid_match else None

    resiliency_score = _regex_resiliency_score(clean_text)

    logger.debug("Extracted exit_status: %s (regex)", exit_status)
    logger.debug("Extracted run_uuid: %s (regex)", run_uuid)
    logger.debug("Extracted resiliency_score: %s (regex)", resiliency_score)
    return TelemetryResult(
        exit_status=exit_status,
        run_uuid=run_uuid,
        resiliency_score=resiliency_score,
    )


def _regex_resiliency_score(text: str) -> Optional[float]:
    """
    Read resiliency_score, pairing it with total_slos from the same report.

    Both keys are read from the top level of overall_resiliency_report, so a
    nested object's keys can't be mixed in. Without that report, the first
    resiliency_score in the text is used and total_slos is treated as missing.
    """
    report_match = _OVERALL_REPORT_RE.search(text)
    if report_match is None:
        score_match = _RESILIENCY_SCORE_RE.search(text)
        return float(score_match.group(1)) if score_match else None

    top_level = _top_level_body(text, report_match.end())
    score_match = _RESILIENCY_SCORE_RE.search(top_level)
    if score_match is None:
        return None
    slos_match = _TOTAL_SLOS_RE.search(top_level)
    total_slos = int(slos_match.group(1)) if slos_match else None
    return _measured_score(float(score_match.group(1)), total_slos)


def _top_level_body(text: str, start: int) -> str:
    """
    Text of the object opened just before `start`, without nested objects or
    arrays. Reads to the end of the text if the object is never closed, since
    this fallback runs on truncated logs.
    """
    depth = 0
    in_string = False
    escaped = False
    top_level = []
    for char in text[start:]:
        if in_string:
            if depth == 0:
                top_level.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            if depth == 0:
                top_level.append(char)
        elif char in "{[":
            depth += 1
        elif char in "}]":
            if depth == 0:
                break
            depth -= 1
        elif depth == 0:
            top_level.append(char)
    return "".join(top_level)
