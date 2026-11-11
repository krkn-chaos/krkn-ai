"""Tests for krkn_ai.chaos_engines.telemetry_parser"""

import json

import pytest

from krkn_ai.chaos_engines.telemetry_parser import (
    extract_graph_telemetry,
    extract_telemetry_from_log,
    strip_ansi,
    _try_json_extraction,
    _try_regex_extraction,
)


def _graph_failure(node, status):
    """The line krknctl graph run prints for a failed node (v0.14.2-beta)."""
    return (
        f"scenario {node} at step 1 with exit status {status}, "
        f"check log file krknctl-{node}-123.log.\n"
    )


def _node_log(status, unrecovered):
    return "Chaos data:" + json.dumps(
        {
            "telemetry": {
                "scenarios": [
                    {
                        "exit_status": status,
                        "affected_pods": {"unrecovered": unrecovered, "error": None},
                    }
                ],
                "error_logs": [],
            }
        }
    )


class TestExtractGraphTelemetry:
    """krknctl graph run exits 0 when a node fails, and only says so in its output."""

    def test_no_failed_node_keeps_krknctl_returncode(self):
        result = extract_graph_telemetry("Release the krkn 0\nEXITING 0\n", 0)
        assert result.exit_status == 0
        assert result.recovery_failed is False

    def test_krknctl_error_without_node_lines_keeps_returncode(self):
        log = "Error: failed to validate scenario: pod-scenarios\n"
        assert extract_graph_telemetry(log, 1).exit_status == 1

    @pytest.mark.parametrize("returncode", [1, -15])
    def test_krknctl_failure_is_not_hidden_by_a_scorable_node(
        self, returncode, tmp_path, monkeypatch
    ):
        """krknctl exits 0 when nodes fail, so a nonzero exit (its own error,
        or the run being cancelled) is the graph's result even when a node
        printed exit status 2 or a recovery failure."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-b-123.log").write_text(_node_log(1, [{"pod_name": "x"}]))
        log = _graph_failure("alerts", 2) + _graph_failure("b", 1)
        result = extract_graph_telemetry(log, returncode)
        assert result.exit_status == returncode
        assert result.recovery_failed is False

    def test_failed_node_sets_exit_status_when_krknctl_exits_zero(self):
        result = extract_graph_telemetry(_graph_failure("bad-node", 1), 0)
        assert result.exit_status == 1
        assert result.recovery_failed is False

    def test_exit_2_node_is_reported(self):
        assert extract_graph_telemetry(_graph_failure("alerts", 2), 0).exit_status == 2

    @pytest.mark.parametrize(
        "lines",
        [
            _graph_failure("a", 2) + _graph_failure("b", 1),
            _graph_failure("b", 1) + _graph_failure("a", 2),
        ],
    )
    def test_misconfigured_node_wins_over_exit_2_in_any_order(self, lines):
        """Parallel nodes print in completion order; exit 2 is still scored but
        any other code means the run is not usable."""
        assert extract_graph_telemetry(lines, 0).exit_status == 1

    def test_ansi_codes_around_the_line_are_ignored(self):
        log = "\x1b[31m" + _graph_failure("bad", 1) + "\x1b[0m"
        assert extract_graph_telemetry(log, 0).exit_status == 1

    def test_other_text_mentioning_exit_status_is_not_a_node_failure(self):
        log = 'node said: scenario x finished "exit_status": 1\n'
        assert extract_graph_telemetry(log, 0).exit_status == 0

    @pytest.mark.parametrize(
        "line",
        [
            "Release the krkn 3" + _graph_failure("b", 1),
            _graph_failure("b", 1).replace("\n", "\r\n"),
            "\x1b[2K\r" + _graph_failure("b", 1),
        ],
    )
    def test_failure_line_sharing_stdout_with_a_node_is_still_seen(self, line):
        """Parallel nodes share krknctl's stdout. Wrongly seeing a failure is
        visible; missing one is the silent success this exists to stop."""
        assert extract_graph_telemetry(line, 0).exit_status == 1

    @pytest.mark.parametrize("status", [3, 4, 255])
    def test_other_exit_status_is_kept(self, status):
        result = extract_graph_telemetry(_graph_failure("b", status), 0)
        assert result.exit_status == status

    def test_node_id_krkn_ai_generates_is_parsed(self):
        assert extract_graph_telemetry(_graph_failure("rootlr", 1), 0).exit_status == 1

    def test_node_telemetry_status_wins_over_container_status(
        self, tmp_path, monkeypatch
    ):
        """As for a single scenario: a health check or alert can make krkn exit
        non-zero while the scenario itself passed."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-b-123.log").write_text(_node_log(0, []))
        assert extract_graph_telemetry(_graph_failure("b", 3), 0).exit_status == 0

    def test_node_with_telemetry_0_does_not_hide_a_failed_node(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-a-123.log").write_text(_node_log(0, []))
        (tmp_path / "krknctl-b-123.log").write_text(_node_log(1, []))
        log = _graph_failure("a", 3) + _graph_failure("b", 1)
        assert extract_graph_telemetry(log, 0).exit_status == 1

    def test_exit_2_node_with_empty_log_stays_exit_2(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-b-123.log").write_text("")
        log = _graph_failure("b", 2) + (
            "Failed to parse resiliency report from krknctl-b-123.log: "
            "resiliency report marker not found in logs\n"
        )
        assert extract_graph_telemetry(log, 0).exit_status == 2

    def test_named_log_that_is_missing_is_not_treated_as_never_ran(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        log = (
            "Failed to parse resiliency report from krknctl-gone-1.log: "
            "resiliency report marker not found in logs\n"
        )
        assert extract_graph_telemetry(log, 0).exit_status == 0

    def test_node_log_with_a_bad_byte_still_parses_its_telemetry(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-b-123.log").write_bytes(
            b"\xff\n" + _node_log(0, []).encode()
        )
        assert extract_graph_telemetry(_graph_failure("b", 3), 0).exit_status == 0

    def test_color_codes_around_the_failure_text_are_ignored(self):
        """krknctl prints this line in red, so the reset code follows the period."""
        log = "\x1b[91m" + _graph_failure("b", 1).rstrip() + "\x1b[0m\n"
        assert extract_graph_telemetry(log, 0).exit_status == 1

    def test_node_that_never_ran_is_a_failure(self, tmp_path, monkeypatch):
        """krknctl output when a node's image is rejected or its container can't
        be created: no failure line, an empty log, exit 0."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-ok-1.log").write_text("EXITING 0\n")
        (tmp_path / "krknctl-bad-2.log").write_text("")
        log = (
            "Failed to parse resiliency report from krknctl-ok-1.log: "
            "resiliency report marker not found in logs\n"
            "⛔  image REJECTED: signature could not be verified\n"
            "Failed to parse resiliency report from krknctl-bad-2.log: "
            "resiliency report marker not found in logs\n"
        )
        result = extract_graph_telemetry(log, 0)
        assert result.exit_status == 1
        assert result.recovery_failed is False

    def test_node_that_ran_with_no_report_is_not_a_failure(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-ok-1.log").write_text("EXITING 0\n")
        log = (
            "Failed to parse resiliency report from krknctl-ok-1.log: "
            "resiliency report marker not found in logs\n"
        )
        assert extract_graph_telemetry(log, 0).exit_status == 0

    @pytest.mark.parametrize(
        "content",
        [
            b"\xff\xfe not utf-8",
            b'Chaos data: {"telemetry": {"scenarios": [{"exit_status": 1}], '
            b'"overall_resiliency_report": {"resiliency_score": "n/a"}}}',
        ],
    )
    def test_unreadable_node_log_does_not_crash_the_run(
        self, tmp_path, monkeypatch, content
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-b-123.log").write_bytes(content)
        result = extract_graph_telemetry(_graph_failure("b", 1), 0)
        assert result.exit_status == 1
        assert result.recovery_failed is False

    def test_unrecovered_targets_in_node_log_count_as_recovery_failure(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-bad-123.log").write_text(
            _node_log(1, [{"pod_name": "shipping"}])
        )
        result = extract_graph_telemetry(_graph_failure("bad", 1), 0)
        assert result.exit_status == 1
        assert result.recovery_failed is True

    def test_node_log_without_unrecovered_targets_stays_misconfiguration(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-bad-123.log").write_text(_node_log(1, []))
        result = extract_graph_telemetry(_graph_failure("bad", 1), 0)
        assert result.exit_status == 1
        assert result.recovery_failed is False

    def test_misconfigured_node_wins_over_a_recovery_failure(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "krknctl-recovery-123.log").write_text(
            _node_log(1, [{"pod_name": "shipping"}])
        )
        (tmp_path / "krknctl-setup-123.log").write_text(_node_log(1, []))
        log = _graph_failure("recovery", 1) + _graph_failure("setup", 1)
        result = extract_graph_telemetry(log, 0)
        assert result.exit_status == 1
        assert result.recovery_failed is False

    def test_missing_node_log_is_not_a_crash(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = extract_graph_telemetry(_graph_failure("gone", 1), 0)
        assert result.exit_status == 1
        assert result.recovery_failed is False

    def test_node_log_is_read_from_the_given_log_dir(self, tmp_path, monkeypatch):
        """The runner points krknctl at a per-run directory; node logs are read
        from there, not from the process working directory (#160)."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        (run_dir / "krknctl-b-123.log").write_text(_node_log(1, [{"pod_name": "x"}]))
        result = extract_graph_telemetry(
            _graph_failure("b", 1), 0, log_dir=str(run_dir)
        )
        assert result.exit_status == 1
        assert result.recovery_failed is True

    def test_node_that_never_ran_is_found_in_the_given_log_dir(
        self, tmp_path, monkeypatch
    ):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        monkeypatch.chdir(tmp_path)
        (run_dir / "krknctl-bad-2.log").write_text("")
        log = (
            "Failed to parse resiliency report from krknctl-bad-2.log: "
            "resiliency report marker not found in logs\n"
        )
        assert extract_graph_telemetry(log, 0, log_dir=str(run_dir)).exit_status == 1

    def test_node_log_path_cannot_leave_the_given_log_dir(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (tmp_path / "outside.log").write_text(_node_log(1, [{"pod_name": "x"}]))
        log = (
            "scenario evil at step 1 with exit status 1, "
            "check log file ../outside.log.\n"
        )
        result = extract_graph_telemetry(log, 0, log_dir=str(run_dir))
        assert result.recovery_failed is False

    def test_node_log_path_cannot_leave_the_working_directory(
        self, tmp_path, monkeypatch
    ):
        work = tmp_path / "work"
        work.mkdir()
        monkeypatch.chdir(work)
        (tmp_path / "outside.log").write_text(_node_log(1, [{"pod_name": "x"}]))
        log = (
            "scenario evil at step 1 with exit status 1, "
            "check log file ../outside.log.\n"
        )
        assert extract_graph_telemetry(log, 0).recovery_failed is False


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
        result = extract_telemetry_from_log(log, 0)
        assert result.exit_status == 2
        assert result.run_uuid == "run-123"
        assert result.resiliency_score is None

    def test_skips_empty_json_before_telemetry(self):
        log = """
Chaos data:
{}
{"telemetry": {"run_uuid": "run-456", "scenarios": [{"exit_status": 2}]}}
"""
        result = extract_telemetry_from_log(log, 0)
        assert result.exit_status == 2
        assert result.run_uuid == "run-456"

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
        result = extract_telemetry_from_log(log, 0)
        assert result.exit_status == 2
        assert result.run_uuid == "run-789"

    def test_handles_ansi_codes_in_json_block(self):
        log = (
            "2026-06-02 11:10:39 [\x1b[37mINFO\x1b[0m] Chaos data:\n"
            '{"telemetry": {"run_uuid": "abc-123", '
            '"scenarios": [{"exit_status": 1}]}}\x1b[0m\n'
        )
        result = extract_telemetry_from_log(log, 0)
        assert result.exit_status == 1
        assert result.run_uuid == "abc-123"

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
        result = extract_telemetry_from_log(log, 0)
        assert result.exit_status == 3
        assert result.run_uuid == "uuid-ansi"

    def test_no_marker_returns_default(self):
        log = "some random log without the marker"
        result = extract_telemetry_from_log(log, -1)
        assert result.exit_status == -1
        assert result.run_uuid is None

    def test_truncated_json_falls_back_to_regex(self):
        log = """
Chaos data:
{"telemetry": {"run_uuid": "regex-uuid", "scenarios": [{"exit_status": 5}]}
"""
        result = extract_telemetry_from_log(log, 99)
        assert result.exit_status == 5
        assert result.run_uuid == "regex-uuid"

    def test_completely_malformed_returns_default(self):
        log = """
Chaos data:
not json at all, just garbage text
"""
        result = extract_telemetry_from_log(log, 42)
        assert result.exit_status == 42
        assert result.run_uuid is None

    def test_exit_status_zero_is_not_confused_with_falsy(self):
        log = """
Chaos data:
{"telemetry": {"run_uuid": "zero-run", "scenarios": [{"exit_status": 0}]}}
"""
        result = extract_telemetry_from_log(log, -1)
        assert result.exit_status == 0
        assert result.run_uuid == "zero-run"

    def test_scenarios_as_non_list_skipped(self):
        """If scenarios is a dict instead of list, skip to next candidate or regex."""
        log = """
Chaos data:
{"telemetry": {"run_uuid": "bad", "scenarios": {"exit_status": 2}}}
{"telemetry": {"run_uuid": "good", "scenarios": [{"exit_status": 4}]}}
"""
        result = extract_telemetry_from_log(log, 0)
        assert result.exit_status == 4
        assert result.run_uuid == "good"

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
        result = extract_telemetry_from_log(log, -1)
        assert result.exit_status == 0
        assert result.run_uuid == "24f33551-128f-49c2-b668-1714e937bdde"


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
        assert result.exit_status == 99
        assert result.run_uuid == "x"


class TestRegexExtraction:
    """Tests specifically for the regex fallback path."""

    def test_finds_exit_status_and_uuid(self):
        text = '"exit_status": 3, "run_uuid": "abc-def"'
        result = _try_regex_extraction(text)
        assert result.exit_status == 3
        assert result.run_uuid == "abc-def"

    def test_finds_exit_status_without_uuid(self):
        text = '"exit_status": 7'
        result = _try_regex_extraction(text)
        assert result.exit_status == 7
        assert result.run_uuid is None

    def test_returns_none_when_no_exit_status(self):
        text = "no relevant keys here"
        assert _try_regex_extraction(text) is None

    def test_handles_negative_exit_status(self):
        text = '"exit_status": -1, "run_uuid": "neg-test"'
        result = _try_regex_extraction(text)
        assert result.exit_status == -1
        assert result.run_uuid == "neg-test"

    def test_handles_ansi_around_values(self):
        text = '\x1b[37m"exit_status"\x1b[0m: 5, "run_uuid": "ansi-uuid"'
        result = _try_regex_extraction(text)
        assert result.exit_status == 5
        assert result.run_uuid == "ansi-uuid"

    def test_extracts_resiliency_score(self):
        text = '"exit_status": 0, "run_uuid": "u1", "resiliency_score": 85.5'
        result = _try_regex_extraction(text)
        assert result.resiliency_score == 85.5

    def test_resiliency_score_none_when_absent(self):
        text = '"exit_status": 0, "run_uuid": "u2"'
        result = _try_regex_extraction(text)
        assert result.resiliency_score is None


class TestResiliencyScoreExtraction:
    """Tests for resiliency score extraction from telemetry."""

    def test_json_extracts_resiliency_score(self):
        log = """
Chaos data:
{
  "telemetry": {
    "run_uuid": "r1",
    "scenarios": [{"exit_status": 0}],
    "overall_resiliency_report": {
      "resiliency_score": 100,
      "passed_slos": 27,
      "total_slos": 27
    }
  }
}
"""
        result = extract_telemetry_from_log(log, -1)
        assert result.exit_status == 0
        assert result.run_uuid == "r1"
        assert result.resiliency_score == 100.0

    def test_json_resiliency_score_none_when_report_absent(self):
        log = """
Chaos data:
{"telemetry": {"run_uuid": "r2", "scenarios": [{"exit_status": 0}]}}
"""
        result = extract_telemetry_from_log(log, -1)
        assert result.resiliency_score is None

    def test_json_resiliency_score_fractional(self):
        log = """
Chaos data:
{
  "telemetry": {
    "run_uuid": "r3",
    "scenarios": [{"exit_status": 0}],
    "overall_resiliency_report": {"resiliency_score": 72.5}
  }
}
"""
        result = extract_telemetry_from_log(log, -1)
        assert result.resiliency_score == 72.5


@pytest.mark.parametrize(
    "snapshot, errors, expected",
    [
        ({"unrecovered": [{"pod_name": "shipping"}], "error": None}, [], True),
        ({"unrecovered": [], "error": None}, [], False),
        (
            {"unrecovered": [{"pod_name": "shipping"}], "error": "injection failed"},
            [],
            False,
        ),
        (
            {"unrecovered": [{"pod_name": "shipping"}], "error": None},
            [{"message": "setup failed"}],
            False,
        ),
        ({"unrecovered": ["invalid"], "error": None}, [], False),
    ],
)
def test_recovery_failure_requires_structured_evidence(snapshot, errors, expected):
    log = "Chaos data:" + json.dumps(
        {
            "telemetry": {
                "scenarios": [{"exit_status": 1, "affected_pods": snapshot}],
                "error_logs": errors,
                "overall_resiliency_report": {"resiliency_score": 100},
            }
        }
    )

    result = extract_telemetry_from_log(log, 1)

    assert result.exit_status == 1
    assert result.recovery_failed is expected


def test_regex_fallback_does_not_infer_recovery_failure():
    result = extract_telemetry_from_log(
        'Chaos data: "exit_status": 1, "unrecovered": [{"pod_name": "shipping"}]',
        1,
    )
    assert result.recovery_failed is False


def test_error_in_another_snapshot_prevents_recovery_classification():
    log = "Chaos data:" + json.dumps(
        {
            "telemetry": {
                "scenarios": [
                    {
                        "exit_status": 1,
                        "affected_pods": {"unrecovered": [{"pod_name": "shipping"}]},
                        "affected_vmis": {"error": "target lookup failed"},
                    }
                ]
            }
        }
    )
    assert extract_telemetry_from_log(log, 1).recovery_failed is False
