import pandas as pd

from krkn_ai.dashboard.tabs.detailed_scenarios import (
    create_runtime_telemetry_plot,
    create_success_timeline_plot,
)


def test_create_runtime_telemetry_plot_empty():
    assert create_runtime_telemetry_plot(pd.DataFrame()) is None
    assert create_runtime_telemetry_plot(None) is None


def test_create_runtime_telemetry_plot_valid():
    df = pd.DataFrame(
        {
            "seconds_into_scenario": [1.0, 2.0],
            "response_time": [0.1, 0.2],
            "service": ["svc1", "svc2"],
            "success": [True, False],
            "scenario_id": ["1", "1"],
            "error": ["None", "timeout"],
            "timestamp": ["12:00:00", "12:00:01"],
            "status_code": [200, 500],
        }
    )
    fig = create_runtime_telemetry_plot(df)
    assert fig is not None


def test_create_success_timeline_plot_empty():
    assert create_success_timeline_plot(pd.DataFrame()) is None


def test_create_success_timeline_plot_valid():
    df = pd.DataFrame(
        {
            "seconds_into_scenario": [1.0, 2.0],
            "service": ["svc1", "svc2"],
            "success": [True, False],
            "scenario_id": ["1", "1"],
        }
    )
    fig = create_success_timeline_plot(df)
    assert fig is not None
