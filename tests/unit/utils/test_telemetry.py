from krkn_ai.utils.telemetry import TelemetryExtractor


def test_extract_telemetry_success():
    log = """
    Some random noise before
    {
        "telemetry": {
            "run_uuid": "test-uuid-123",
            "scenarios": [{"exit_status": 0}]
        }
    }
    Some noise after
    """
    exit_status, run_uuid, data = TelemetryExtractor.extract_telemetry(log)
    assert exit_status == 0
    assert run_uuid == "test-uuid-123"


def test_extract_telemetry_last_win():
    log = """
    First block (should be ignored):
    {
        "telemetry": {
            "run_uuid": "first-uuid",
            "scenarios": [{"exit_status": 1}]
        }
    }
    Second block (Last-Win):
    {
        "telemetry": {
            "run_uuid": "last-uuid",
            "scenarios": [{"exit_status": 0}]
        }
    }
    """
    exit_status, run_uuid, data = TelemetryExtractor.extract_telemetry(log)
    assert exit_status == 0
    assert run_uuid == "last-uuid"


def test_extract_telemetry_with_ansi_colors():
    log = '\x1b[32mSome color\x1b[0m {"telemetry": {"run_uuid": "u", "scenarios": [{"exit_status": 2}]}}'
    exit_status, _, _ = TelemetryExtractor.extract_telemetry(log)
    assert exit_status == 2


def test_extract_telemetry_not_found_returns_default():
    log = "No telemetry here"
    exit_status, run_uuid, data = TelemetryExtractor.extract_telemetry(
        log, default_return_code=404
    )
    assert exit_status == 404
    assert run_uuid is None


def test_extract_telemetry_invalid_json_after_marker_skips():
    log = """
    Noise with a { fake brace
    Then real telemetry:
    {
        "telemetry": {
            "run_uuid": "real",
            "scenarios": [{"exit_status": 0}]
        }
    }
    """
    exit_status, run_uuid, _ = TelemetryExtractor.extract_telemetry(log)
    assert exit_status == 0
    assert run_uuid == "real"
