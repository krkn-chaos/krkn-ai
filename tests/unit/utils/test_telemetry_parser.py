"""Tests for krkn_ai.utils.telemetry_parser"""

from krkn_ai.utils.telemetry_parser import (
    extract_telemetry_from_log,
    strip_ansi,
    _try_json_extraction,
    _try_regex_extraction,
)


class TestStripAnsi:
    def test_removes_color_codes(self):
        text = "\x1b[37mINFO\x1b[0m some message"
        assert strip_ansi(text) == "INFO some message"

    def test_no_op_on_clean_text(self):
        text = "no ansi here"
        assert strip_ansi(text) == text

    def test_removes_multiple_codes(self):
        text = "\x1b[1m\x1b[33mWARNING\x1b[0m\x1b[0m"
        assert strip_ansi(text) == "WARNING"


class TestExtractTelemetryFromLog:
    """Test the full fallback chain: JSON -> regex -> default"""

    def test_multiline_telemetry_json(self):
        log = """
Chaos data:
{
  "telemetry": {
    "run_uuid": "run-123",
    "scenarios": [
      {"exit_status": 2}
    ]
  }
}
"""
        assert extract_telemetry_from_log(log, 0) == (2, "run-123")

    def test_skips_empty_json_before_telemetry(self):
        log = """
Chaos data:
{}
{"telemetry": {"run_uuid": "run-456", "scenarios": [{"exit_status": 2}]}}
"""
        assert extract_telemetry_from_log(log, 0) == (2, "run-456")

    def test_handles_brace_inside_string_value(self):
        log = """
Chaos data:
{
  "telemetry": {
    "run_uuid": "run-789",
    "scenarios": [
      {
        "exit_status": 2,
        "message": "output had } inside"
      }
    ]
  }
}
"""
        assert extract_telemetry_from_log(log, 0) == (2, "run-789")

    def test_handles_ansi_codes_in_json_block(self):
        log = (
            "2026-06-02 11:10:39 [\x1b[37mINFO\x1b[0m] Chaos data:\n"
            '{"telemetry": {"run_uuid": "abc-123", '
            '"scenarios": [{"exit_status": 1}]}}\x1b[0m\n'
        )
        assert extract_telemetry_from_log(log, 0) == (1, "abc-123")

    def test_handles_ansi_after_closing_brace(self):
        log = (
            "Chaos data:\n"
            "{\n"
            '  "telemetry": {\n'
            '    "run_uuid": "uuid-ansi",\n'
            '    "scenarios": [{"exit_status": 3}]\n'
            "  }\n"
            "}\x1b[0m\n"
        )
        assert extract_telemetry_from_log(log, 0) == (3, "uuid-ansi")

    def test_no_marker_returns_default(self):
        log = "some random log without the marker"
        assert extract_telemetry_from_log(log, -1) == (-1, None)

    def test_truncated_json_falls_back_to_regex(self):
        log = """
Chaos data:
{"telemetry": {"run_uuid": "regex-uuid", "scenarios": [{"exit_status": 5}]}
"""
        assert extract_telemetry_from_log(log, 99) == (5, "regex-uuid")

    def test_completely_malformed_returns_default(self):
        log = """
Chaos data:
not json at all, just garbage text
"""
        assert extract_telemetry_from_log(log, 42) == (42, None)

    def test_exit_status_zero_is_not_confused_with_falsy(self):
        log = """
Chaos data:
{"telemetry": {"run_uuid": "zero-run", "scenarios": [{"exit_status": 0}]}}
"""
        assert extract_telemetry_from_log(log, -1) == (0, "zero-run")

    def test_scenarios_as_non_list_skipped(self):
        """If scenarios is a dict instead of list, skip to next candidate or regex."""
        log = """
Chaos data:
{"telemetry": {"run_uuid": "bad", "scenarios": {"exit_status": 2}}}
{"telemetry": {"run_uuid": "good", "scenarios": [{"exit_status": 4}]}}
"""
        assert extract_telemetry_from_log(log, 0) == (4, "good")

    def test_real_world_log_with_ansi(self):
        """Simulates the structure of a real krkn log with ANSI codes throughout."""
        log = (
            "2026-06-02 11:10:39,244 [\x1b[37mINFO\x1b[0m] Chaos data:\n"
            "{\n"
            '    "telemetry": {\n'
            '        "scenarios": [\n'
            "            {\n"
            '                "exit_status": 0,\n'
            '                "scenario": "scenarios/container_scenario.yaml"\n'
            "            }\n"
            "        ],\n"
            '        "run_uuid": "24f33551-128f-49c2-b668-1714e937bdde"\n'
            "    }\n"
            "}\x1b[0m\n"
            " _              _\n"
        )
        assert extract_telemetry_from_log(log, -1) == (
            0,
            "24f33551-128f-49c2-b668-1714e937bdde",
        )


class TestJsonExtraction:
    """Tests specifically for the JSON extraction path."""

    def test_returns_none_when_no_json_found(self):
        assert _try_json_extraction("no braces here", 0) is None

    def test_skips_non_dict_json(self):
        assert _try_json_extraction("[1, 2, 3]", 0) is None

    def test_skips_dict_without_telemetry(self):
        assert _try_json_extraction('{"foo": "bar"}', 0) is None

    def test_uses_default_when_exit_status_missing(self):
        text = '{"telemetry": {"run_uuid": "x", "scenarios": [{"other": 1}]}}'
        result = _try_json_extraction(text, 99)
        assert result == (99, "x")


class TestRegexExtraction:
    """Tests specifically for the regex fallback path."""

    def test_finds_exit_status_and_uuid(self):
        text = '"exit_status": 3, "run_uuid": "abc-def"'
        assert _try_regex_extraction(text) == (3, "abc-def")

    def test_finds_exit_status_without_uuid(self):
        text = '"exit_status": 7'
        assert _try_regex_extraction(text) == (7, None)

    def test_returns_none_when_no_exit_status(self):
        text = "no relevant keys here"
        assert _try_regex_extraction(text) is None

    def test_handles_negative_exit_status(self):
        text = '"exit_status": -1, "run_uuid": "neg-test"'
        assert _try_regex_extraction(text) == (-1, "neg-test")

    def test_handles_ansi_around_values(self):
        text = '\x1b[37m"exit_status"\x1b[0m: 5, "run_uuid": "ansi-uuid"'
        assert _try_regex_extraction(text) == (5, "ansi-uuid")
