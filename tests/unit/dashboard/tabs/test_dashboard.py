import pandas as pd

from krkn_ai.dashboard.tabs.dashboard import (
    create_fitness_evolution_plot,
    create_scenario_distribution_plot,
    create_scenario_fitness_variation_plot,
    create_baseline_delta_plot,
    create_improvement_trend_plot,
)


def test_create_fitness_evolution_plot_empty():
    assert create_fitness_evolution_plot(pd.DataFrame()) is None


def test_create_fitness_evolution_plot_valid():
    df = pd.DataFrame(
        {
            "generation_id": [0, 0, 1],
            "fitness_score": [1.0, 2.0, 3.0],
        }
    )
    fig = create_fitness_evolution_plot(df)
    assert fig is not None


def test_create_scenario_distribution_plot_empty():
    assert create_scenario_distribution_plot(pd.DataFrame()) is None


def test_create_scenario_distribution_plot_valid():
    df = pd.DataFrame(
        {
            "scenario": ["A", "B", "A"],
        }
    )
    fig = create_scenario_distribution_plot(df)
    assert fig is not None


def test_create_scenario_fitness_variation_plot_empty():
    assert create_scenario_fitness_variation_plot(pd.DataFrame()) is None


def test_create_scenario_fitness_variation_plot_valid():
    df = pd.DataFrame(
        {
            "scenario": ["A", "B", "A"],
            "generation_id": [0, 0, 1],
            "fitness_score": [1.0, 2.0, 3.0],
        }
    )
    fig = create_scenario_fitness_variation_plot(df)
    assert fig is not None


def test_create_baseline_delta_plot_empty():
    assert create_baseline_delta_plot(pd.DataFrame()) is None


def test_create_baseline_delta_plot_valid():
    df = pd.DataFrame(
        {
            "scenario_id": ["baseline", "1"],
            "scenario": ["baseline", "A"],
            "fitness_score": [1.0, 2.0],
        }
    )
    fig = create_baseline_delta_plot(df)
    assert fig is not None


def test_create_improvement_trend_plot_empty():
    assert create_improvement_trend_plot(pd.DataFrame()) is None


def test_create_improvement_trend_plot_valid():
    df = pd.DataFrame(
        {
            "scenario_id": ["baseline", "1"],
            "generation_id": [pd.NA, 0],
            "fitness_score": [1.0, 2.0],
        }
    )
    fig = create_improvement_trend_plot(df)
    assert fig is not None
