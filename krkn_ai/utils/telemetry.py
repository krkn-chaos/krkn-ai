import json
import re
from typing import Optional, Tuple, Dict, Any
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class TelemetryExtractor:
    """
    Service for robustly extracting JSON telemetry data from Krkn execution logs.
    """

    # Regex to strip ANSI escape sequences (colors, etc.)
    ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    @staticmethod
    def clean_log(log_text: str) -> str:
        """Removes ANSI escape codes and terminal artifacts."""
        return TelemetryExtractor.ANSI_ESCAPE.sub("", log_text)

    @classmethod
    def extract_telemetry(
        cls, log_text: str
    ) -> Tuple[int, Optional[str], Optional[Dict[str, Any]]]:
        """
        Extracts exit_status, run_uuid, and full telemetry data from log text.

        Returns:
            Tuple of (exit_status, run_uuid, full_data_dict)
            Defaults to (default_return_code, None, None) if not found.
        """
        cleaned_log = cls.clean_log(log_text)

        # Look for the "Chaos data:" marker
        # We search from the end of the log to find the most recent telemetry block
        marker = "Chaos data:"
        if marker not in cleaned_log:
            logger.warning("Telemetry marker '%s' not found in log", marker)
            return -1, None, None

        # Split by marker and take the last part (latest telemetry)
        parts = cleaned_log.rsplit(marker, 1)
        potential_json_area = parts[1].strip()

        # Try to find a valid JSON block starting from any '{' in the potential area
        for i, char in enumerate(potential_json_area):
            if char == "{":
                json_str = cls._find_json_block(potential_json_area[i:])
                if json_str:
                    try:
                        data = json.loads(json_str)
                        telemetry = data.get("telemetry", {})
                        scenarios = telemetry.get("scenarios", [])

                        exit_status = -1
                        run_uuid = telemetry.get("run_uuid")

                        if scenarios:
                            exit_status = scenarios[0].get("exit_status", -1)

                        return exit_status, run_uuid, data
                    except json.JSONDecodeError:
                        # This '{' didn't lead to valid JSON, keep looking
                        continue

        logger.warning("Could not identify valid JSON block after telemetry marker")
        return -1, None, None

    @staticmethod
    def _find_json_block(text: str) -> Optional[str]:
        """
        Extracts a single JSON object from text by balancing braces.
        Assumes text starts with '{'.
        """
        if not text or text[0] != "{":
            return None

        brace_count = 0
        for i, char in enumerate(text):
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return text[: i + 1]
        return None
