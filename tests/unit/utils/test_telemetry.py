import json
import pytest
from krkn_ai.utils.telemetry import TelemetryExtractor

def test_extract_telemetry_success():
    log_content = """Some dummy logs before chaos data.
Chaos data:
{
  "telemetry": {
    "run_uuid": "test-uuid-1234",
    "scenarios": [
      {
        "name": "cpu-hog",
        "exit_status": 0
      }
    ]
  }
}
Some dummy logs after chaos data.
"""
    exit_status, run_uuid, chaos_data = TelemetryExtractor.extract_telemetry(log_content)
    assert exit_status == 0
    assert run_uuid == "test-uuid-1234"
    assert chaos_data is not None
    assert chaos_data["telemetry"]["scenarios"][0]["name"] == "cpu-hog"

def test_extract_telemetry_missing_chaos_data():
    log_content = "Some logs that do not contain chaos data at all."
    exit_status, run_uuid, chaos_data = TelemetryExtractor.extract_telemetry(log_content)
    assert exit_status == 1
    assert run_uuid is None
    assert chaos_data is None

def test_extract_telemetry_invalid_json():
    log_content = """Chaos data:
{
  "telemetry": {
    "run_uuid": "test-uuid-1234",
    "scenarios": [
"""
    exit_status, run_uuid, chaos_data = TelemetryExtractor.extract_telemetry(log_content)
    assert exit_status == 1
    assert run_uuid is None
    assert chaos_data is None
