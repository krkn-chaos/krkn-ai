import pytest
from krkn_ai.utils.telemetry import TelemetryExtractor


def test_extract_telemetry_success():
    log = """
    Some random noise before
    Chaos data:
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
    assert data["telemetry"]["run_uuid"] == "test-uuid-123"


def test_extract_telemetry_with_ansi_colors():
    log = (
        '\x1b[32mChaos data:\x1b[0m {"telemetry": {"scenarios": [{"exit_status": 2}]}}'
    )
    exit_status, _, _ = TelemetryExtractor.extract_telemetry(log)
    assert exit_status == 2


def test_extract_telemetry_with_noise_and_interleaved_braces():
    log = """
    Debug: { "fake": "json" }
    Chaos data: 
    This is noise { but this is valid: 
    {
        "telemetry": {
            "run_uuid": "uuid",
            "scenarios": [{"exit_status": 1}]
        }
    }
    }
    """
    # The parser should find the first valid JSON block after the marker
    exit_status, run_uuid, _ = TelemetryExtractor.extract_telemetry(log)
    assert exit_status == 1
    assert run_uuid == "uuid"


def test_extract_telemetry_not_found():
    log = "No telemetry here"
    exit_status, run_uuid, data = TelemetryExtractor.extract_telemetry(log)
    assert exit_status == -1
    assert run_uuid is None
    assert data is None


def test_extract_telemetry_invalid_json():
    log = "Chaos data: { invalid json"
    exit_status, _, _ = TelemetryExtractor.extract_telemetry(log)
    assert exit_status == -1
