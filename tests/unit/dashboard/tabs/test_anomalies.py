import pandas as pd

from krkn_ai.dashboard.tabs.anomalies import (
    _extract_baseline,
    detect_fitness_iqr_anomalies,
    create_anomaly_overview_plot,
    MODE_ZSCORE,
    MODE_PCT,
)


def test_extract_baseline():
    df = pd.DataFrame(
        {
            "scenario_id": ["1", "baseline"],
            "fitness_score": [1.0, 0.5],
        }
    )
    baseline = _extract_baseline(df)
    assert baseline["fitness_score"] == 0.5


def test_extract_baseline_empty():
    df = pd.DataFrame()
    baseline = _extract_baseline(df)
    assert baseline["fitness_score"] is None


def _results_df(**kwargs):
    base = {
        "scenario_id": ["1", "2", "3", "4"],
        "scenario": ["s1", "s2", "s3", "s4"],
        "generation_id": [0, 0, 0, 0],
        "fitness_score": [1.0, 1.1, 1.05, -5.0],
    }
    base.update(kwargs)
    return pd.DataFrame(base)


def test_detect_fitness_iqr_empty():
    assert detect_fitness_iqr_anomalies(pd.DataFrame()).empty


def test_detect_fitness_iqr_zscore_detects_outlier():
    df = _results_df()
    out = detect_fitness_iqr_anomalies(df, baseline_fitness=1.0, mode=MODE_ZSCORE)
    assert not out.empty
    assert "Low Fitness (IQR)" in out["anomaly_type"].values


def test_detect_fitness_iqr_pct_mode():
    df = _results_df()
    out = detect_fitness_iqr_anomalies(df, baseline_fitness=1.0, mode=MODE_PCT)
    assert not out.empty


def test_detect_fitness_iqr_filters_baseline_row():
    df = pd.DataFrame(
        {
            "scenario_id": ["baseline"],
            "scenario": ["baseline"],
            "generation_id": [0],
            "fitness_score": [1.0],
        }
    )
    assert detect_fitness_iqr_anomalies(df).empty


def test_create_anomaly_overview_plot_empty():
    assert create_anomaly_overview_plot(pd.DataFrame()) is None


def test_create_anomaly_overview_plot_valid():
    df = pd.DataFrame(
        {
            "scenario_id": [1],
            "scenario": ["A"],
            "anomaly_type": ["Type"],
            "severity": ["High"],
            "value": [1.0],
            "detail": ["detail"],
            "z_score": [1.5],
            "threshold": [0.0],
        }
    )
    fig = create_anomaly_overview_plot(df)
    assert fig is not None
