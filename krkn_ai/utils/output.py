import glob
import re

from krkn_ai.models.app import CommandRunResult

_INVALID_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")
_PLACEHOLDERS = ("%g", "%s", "%c")


def _sanitize_filename_component(value: str) -> str:
    """Replace characters that are unsafe for filenames."""
    return _INVALID_FILENAME_CHARS.sub("_", value)


def format_result_filename(fmt: str, command_result: CommandRunResult) -> str:
    """
    Format output filename using placeholders from a CommandRunResult.

    Supported placeholders:
    - %g: Generation ID
    - %s: Scenario ID
    - %c: Scenario Name
    """
    scenario_name = getattr(command_result.scenario, "name", "") or ""
    safe_name = _sanitize_filename_component(str(scenario_name))
    return (
        fmt.replace("%g", str(command_result.generation_id))
        .replace("%s", str(command_result.scenario_id))
        .replace("%c", safe_name)
    )


def fmt_to_glob(fmt: str) -> str:
    """
    Convert a name-format string (with %g/%s/%c placeholders) into a glob
    pattern matching any filename the format string could produce.
    """
    pattern = glob.escape(fmt)
    for placeholder in _PLACEHOLDERS:
        pattern = pattern.replace(placeholder, "*")
    return pattern


def fmt_to_id_regex(fmt: str) -> re.Pattern:
    """
    Convert a name-format string into a compiled, anchored regex with one
    capture group for the %s (scenario ID) placeholder. The capture group
    matches digits only (\\d+). Assumes %s is present in fmt and occurs
    exactly once.
    """
    pattern = re.escape(fmt)
    pattern = pattern.replace("%g", ".*").replace("%s", r"(\d+)").replace("%c", ".*")
    return re.compile(f"^{pattern}$")


def format_duration(duration: float) -> str:
    """
    Format duration in seconds to a human-readable string.
    """
    if duration < 60:
        return f"{duration:.2f} seconds"
    elif duration < 3600:
        return f"{duration / 60:.2f} minutes"
    else:
        return f"{duration / 3600:.2f} hours"
