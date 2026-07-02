"""
Telemetry extraction from Krkn run logs.

Extracts exit_status and run_uuid from the "Chaos data:" JSON telemetry
block emitted by Krkn at the end of a run.

Fallback chain:
  1. JSON decode via raw_decode (handles ANSI codes, trailing garbage)
  2. Regex pattern matching for exit_status / run_uuid keys
  3. Return caller-supplied default
"""

import json
import re
from typing import Optional, Tuple

from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

_EXIT_STATUS_RE = re.compile(r'"exit_status"\s*:\s*(-?\d+)')
_RUN_UUID_RE = re.compile(r'"run_uuid"\s*:\s*"([^"]+)"')

CHAOS_DATA_MARKER = "Chaos data:"


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_ESCAPE_RE.sub("", text)


def extract_telemetry_from_log(
    log: str, default_returncode: int
) -> Tuple[int, Optional[str]]:
    """
    Extract Krkn return code and run_uuid from a run log.

    Fallback chain:
      1. Locate "Chaos data:" marker, strip ANSI, then use JSONDecoder.raw_decode
         to find a valid telemetry JSON object.
      2. If JSON decode fails, use regex to find exit_status and run_uuid values.
      3. Return default_returncode if nothing is found.

    Returns:
        (exit_status, run_uuid) or (default_returncode, None) on failure.
    """
    marker_idx = log.find(CHAOS_DATA_MARKER)
    if marker_idx == -1:
        logger.warning("Could not find '%s' in log", CHAOS_DATA_MARKER)
        return default_returncode, None

    after_marker = log[marker_idx + len(CHAOS_DATA_MARKER) :]

    result = _try_json_extraction(after_marker, default_returncode)
    if result is not None:
        return result

    result = _try_regex_extraction(after_marker)
    if result is not None:
        return result

    logger.warning("No exit_status found in telemetry data")
    return default_returncode, None


def _try_json_extraction(
    text: str, default_returncode: int
) -> Optional[Tuple[int, Optional[str]]]:
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
        logger.debug("Extracted exit_status: %s (json)", exit_status)
        logger.debug("Extracted run_uuid: %s (json)", run_uuid)
        return exit_status, run_uuid

    return None


def _try_regex_extraction(text: str) -> Optional[Tuple[int, Optional[str]]]:
    """
    Fallback: use regex to locate exit_status and run_uuid values
    directly from the raw (or ANSI-contaminated) text.
    """
    clean_text = strip_ansi(text)

    exit_match = _EXIT_STATUS_RE.search(clean_text)
    if not exit_match:
        return None

    exit_status = int(exit_match.group(1))
    uuid_match = _RUN_UUID_RE.search(clean_text)
    run_uuid = uuid_match.group(1) if uuid_match else None

    logger.debug("Extracted exit_status: %s (regex)", exit_status)
    logger.debug("Extracted run_uuid: %s (regex)", run_uuid)
    return exit_status, run_uuid
