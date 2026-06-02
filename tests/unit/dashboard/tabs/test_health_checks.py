import pandas as pd

from krkn_ai.dashboard.tabs.health_checks import (
    create_health_checks_heatmap_plot,
    create_health_checks_trend_plot,
    create_success_vs_failure_plot,
    create_resilience_radar_plot,
    create_response_range_plot,
)


def test_create_health_checks_heatmap_plot_empty():
    assert create_health_checks_heatmap_plot(None) is None
    assert create_health_checks_heatmap_plot(pd.DataFrame()) is None


def test_create_health_checks_heatmap_plot_valid():
    df = pd.DataFrame(
        {
            "scenario_id": [1, 2, 1],
            "component_name": ["A", "A", "B"],
            "average_response_time": [0.1, 0.2, 0.3],
        }
    )
    fig = create_health_checks_heatmap_plot(df)
    assert fig is not None
    assert fig.layout.title.text == "average_response_time Heatmap"


def test_create_health_checks_trend_plot_empty():
    assert create_health_checks_trend_plot(None) is None


def test_create_health_checks_trend_plot_valid():
    df = pd.DataFrame(
        {
            "scenario_id": ["1.0", "2.0"],
            "component_name": ["A", "B"],
            "average_response_time": [0.1, 0.2],
        }
    )
    fig = create_health_checks_trend_plot(df)
    assert fig is not None


def test_create_success_vs_failure_plot_empty():
    assert create_success_vs_failure_plot(None) is None


def test_create_success_vs_failure_plot_valid():
    df = pd.DataFrame(
        {"component_name": ["A"], "success_count": [10], "failure_count": [2]}
    )
    fig = create_success_vs_failure_plot(df)
    assert fig is not None


def test_create_resilience_radar_plot_empty():
    assert create_resilience_radar_plot(None) is None


def test_create_resilience_radar_plot_valid():
    df = pd.DataFrame(
        {"scenario_id": [1], "component_name": ["A"], "average_response_time": [0.1]}
    )
    fig = create_resilience_radar_plot(df)
    assert fig is not None


def test_create_response_range_plot_empty():
    assert create_response_range_plot(None) is None


def test_create_response_range_plot_valid():
    df = pd.DataFrame(
        {
            "component_name": ["A"],
            "min_response_time": [0.1],
            "max_response_time": [0.5],
        }
    )
    fig = create_response_range_plot(df)
    assert fig is not None
