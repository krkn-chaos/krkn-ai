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
import os
import re
from dataclasses import dataclass
from typing import Optional

from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

_EXIT_STATUS_RE = re.compile(r'"exit_status"\s*:\s*(-?\d+)')
_RUN_UUID_RE = re.compile(r'"run_uuid"\s*:\s*"([^"]+)"')
_RESILIENCY_SCORE_RE = re.compile(r'"resiliency_score"\s*:\s*(\d+(?:\.\d+)?)')

CHAOS_DATA_MARKER = "Chaos data:"


@dataclass
class TelemetryResult:
    exit_status: int
    run_uuid: Optional[str] = None
    resiliency_score: Optional[float] = None


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_ESCAPE_RE.sub("", text)


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
                resiliency_score = float(raw)

        logger.debug("Extracted exit_status: %s (json)", exit_status)
        logger.debug("Extracted run_uuid: %s (json)", run_uuid)
        logger.debug("Extracted resiliency_score: %s (json)", resiliency_score)
        return TelemetryResult(
            exit_status=exit_status,
            run_uuid=run_uuid,
            resiliency_score=resiliency_score,
        )

    return None


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

    resiliency_match = _RESILIENCY_SCORE_RE.search(clean_text)
    resiliency_score = float(resiliency_match.group(1)) if resiliency_match else None

    logger.debug("Extracted exit_status: %s (regex)", exit_status)
    logger.debug("Extracted run_uuid: %s (regex)", run_uuid)
    logger.debug("Extracted resiliency_score: %s (regex)", resiliency_score)
    return TelemetryResult(
        exit_status=exit_status,
        run_uuid=run_uuid,
        resiliency_score=resiliency_score,
    )


def extract_telemetry_from_graph_logs(
    log_dir: str, default_returncode: int
) -> TelemetryResult:
    """
    Extract telemetry from a graph run by parsing individual node log files.
    krknctl graph run creates a separate log file per graph node execution.

    Returns the worst return code found across all node logs, with safe fallback.
    """
    if not os.path.exists(log_dir):
        logger.warning("Graph log directory does not exist: %s", log_dir)
        return TelemetryResult(exit_status=default_returncode)

    log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]
    if not log_files:
        logger.warning("No log files found in graph log directory")
        return TelemetryResult(exit_status=default_returncode)

    logger.debug("Found %d log files in graph run", len(log_files))

    worst_returncode = 0
    run_uuid = None
    resiliency_scores = []

    for log_file in log_files:
        log_path = os.path.join(log_dir, log_file)
        try:
            with open(log_path, "r") as f:
                node_log = f.read()

            node_telemetry = extract_telemetry_from_log(node_log, 0)
            node_returncode = node_telemetry.exit_status

            # Track the worst return code seen.
            # Prioritize misconfiguration (non-zero, non-2) over SLO failures (2).
            if node_returncode != 0 and node_returncode != 2:
                worst_returncode = node_returncode
            elif worst_returncode in (0, 2):
                if node_returncode > worst_returncode:
                    worst_returncode = node_returncode

            # Capture UUID from any node (they should all share the same run UUID)
            if node_telemetry.run_uuid and not run_uuid:
                run_uuid = node_telemetry.run_uuid

            if node_telemetry.resiliency_score is not None:
                resiliency_scores.append(node_telemetry.resiliency_score)

            logger.debug("Node %s exit status: %d", log_file, node_returncode)

        except Exception as e:
            logger.warning("Failed to parse log file %s: %s", log_file, e)
            continue

    logger.info(
        "Graph run worst exit status: %d (from %d nodes)",
        worst_returncode,
        len(log_files),
    )
    resiliency_score = (
        sum(resiliency_scores) / len(resiliency_scores) if resiliency_scores else None
    )
    return TelemetryResult(
        exit_status=worst_returncode,
        run_uuid=run_uuid,
        resiliency_score=resiliency_score,
    )
