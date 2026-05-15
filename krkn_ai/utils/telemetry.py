import json
import re
from typing import Optional, Tuple, Dict, Any
from krkn_ai.utils.logger import get_logger
from krkn_ai.models.telemetry import KrknTelemetry

logger = get_logger(__name__)

class TelemetryExtractor:
    """
    Service for robustly extracting JSON telemetry data from Krkn execution logs.
    """

    # Regex to strip ANSI escape sequences (colors, etc.)
    ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    @staticmethod
    def clean_log(log_text: str) -> str:
        """Removes ANSI escape codes and terminal artifacts."""
        return TelemetryExtractor.ANSI_ESCAPE.sub('', log_text)

    @classmethod
    def extract_telemetry(
        cls, log_text: str, default_return_code: int = -1
    ) -> Tuple[int, Optional[str], Optional[Dict[str, Any]]]:
        """
        Extracts exit_status, run_uuid, and full telemetry data from log text.
        Implements Last-Win logic: if multiple valid blocks exist, the last one is returned.
        """
        cleaned_log = cls.clean_log(log_text)
        decoder = json.JSONDecoder()
        
        last_valid_telemetry: Optional[KrknTelemetry] = None
        last_valid_raw: Optional[Dict[str, Any]] = None

        # Scan the log for all potential JSON objects
        cursor = 0
        while cursor < len(cleaned_log):
            try:
                # Find the next possible JSON start
                start_idx = cleaned_log.find('{', cursor)
                if start_idx == -1:
                    break
                
                # Try to decode the JSON object starting at this position
                obj, end_idx = decoder.raw_decode(cleaned_log[start_idx:])
                
                # Validate against Pydantic model
                try:
                    telemetry_model = KrknTelemetry(telemetry=obj.get("telemetry", {}))
                    last_valid_telemetry = telemetry_model
                    last_valid_raw = obj
                    logger.debug("Found valid telemetry block at position %d", start_idx)
                except Exception:
                    # Not our telemetry JSON, keep looking
                    pass
                
                # Move cursor past this object
                cursor = start_idx + end_idx
            except json.JSONDecodeError:
                # Not a valid JSON object at this position, move to next char
                cursor = start_idx + 1

        if last_valid_telemetry and last_valid_raw:
            payload = last_valid_telemetry.telemetry
            exit_status = default_return_code
            if payload.scenarios:
                exit_status = payload.scenarios[0].exit_status
            
            return exit_status, payload.run_uuid, last_valid_raw

        logger.warning("No valid telemetry JSON block found in log")
        return default_return_code, None, None
