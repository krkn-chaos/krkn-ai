import json
from typing import Tuple, Optional
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

class TelemetryExtractor:
    @staticmethod
    def extract_telemetry(log: str) -> Tuple[int, Optional[str], Optional[dict]]:
        """
        Extracts exit_status, run_uuid, and the full chaos_data from the log.
        """
        try:
            # Find the line with "Chaos data:" and extract JSON from next lines
            lines = log.split("\n")
            chaos_data_idx = -1

            for i, line in enumerate(lines):
                if "Chaos data:" in line:
                    chaos_data_idx = i + 1
                    break

            if chaos_data_idx == -1:
                logger.warning("Could not find 'Chaos data:' in log")
                return 1, None, None

            # Extract JSON by counting braces
            json_lines = []
            brace_count = 0
            started = False

            for i in range(chaos_data_idx, len(lines)):
                line = lines[i]

                # Count opening and closing braces
                for char in line:
                    if char == "{":
                        brace_count += 1
                        started = True
                    elif char == "}":
                        brace_count -= 1

                if started:
                    json_lines.append(line)

                # When braces are balanced, we've found the complete JSON
                if started and brace_count == 0:
                    break

            if not json_lines:
                logger.warning("Could not extract JSON content from log")
                return 1, None, None

            # Join all JSON lines into a single string
            json_str = "\n".join(json_lines)
            chaos_data = json.loads(json_str)

            # Extract exit_status from first scenario
            scenarios = chaos_data.get("telemetry", {}).get("scenarios", [])
            run_uuid = chaos_data.get("telemetry", {}).get("run_uuid", None)
            
            if scenarios and len(scenarios) > 0:
                exit_status = scenarios[0].get("exit_status", 1)
                return exit_status, run_uuid, chaos_data

            logger.warning("No exit_status found in telemetry data")
            return 1, run_uuid, chaos_data

        except Exception as e:
            logger.error("Failed to extract return code from run log: %s", e)
            return 1, None, None
