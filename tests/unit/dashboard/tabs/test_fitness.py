import pandas as pd

from krkn_ai.dashboard.tabs.fitness import (
    build_contribution_frame,
    build_query_summary,
    build_weights_frame,
    create_contribution_plot,
    create_query_evolution_plot,
    create_weights_plot,
)


def _items():
    return [
        {
            "name": "pod-restarts:default",
            "category": "availability",
            "query": "q1",
            "type": "range",
            "weight": 0.75,
            "enabled": True,
            "reason": "",
        },
        {
            "name": "node-pressure",
            "category": "node",
            "query": "q2",
            "type": "range",
            "weight": 0.25,
            "enabled": True,
            "reason": "",
        },
        {
            "name": "etcd-no-leader",
            "category": "etcd",
            "query": "q3",
            "type": "range",
            "weight": 0.0,
            "enabled": False,
            "reason": "metric(s) not scraped: etcd_server_has_leader",
        },
    ]


def _df():
    return pd.DataFrame(
        {
            "generation_id": [0, 1],
            "scenario_id": ["1", "2"],
            "scenario": ["pod_scenarios", "pod_scenarios"],
            "slo_0": [2.0, 4.0],
            "slo_1": [1.0, 1.0],
        }
    )


def test_build_contribution_frame_empty():
    assert build_contribution_frame(pd.DataFrame(), _items()).empty
    assert build_contribution_frame(_df(), []).empty


def test_build_contribution_frame_weights_each_query():
    long_df = build_contribution_frame(_df(), _items())
    assert len(long_df) == 4
    first = long_df[
        (long_df["scenario_id"] == "1") & (long_df["name"] == "pod-restarts:default")
    ].iloc[0]
    assert first["raw"] == 2.0
    assert first["contribution"] == 1.5
    # the rejected query has no column and must not appear
    assert "etcd-no-leader" not in set(long_df["name"])


def test_build_contribution_frame_skips_mismatched_columns():
    df = _df().drop(columns=["slo_1"])
    assert build_contribution_frame(df, _items()).empty


def test_create_contribution_plot():
    assert create_contribution_plot(pd.DataFrame()) is None
    assert (
        create_contribution_plot(build_contribution_frame(_df(), _items())) is not None
    )


def test_create_query_evolution_plot():
    long_df = build_contribution_frame(_df(), _items())
    assert create_query_evolution_plot(long_df) is not None
    assert create_query_evolution_plot(long_df, ["node-pressure"]) is not None
    assert create_query_evolution_plot(long_df, ["missing"]) is None


def test_build_query_summary_flags_flat_queries():
    summary = build_query_summary(build_contribution_frame(_df(), _items()))
    flat = summary[summary["name"] == "node-pressure"].iloc[0]
    varying = summary[summary["name"] == "pod-restarts:default"].iloc[0]
    assert bool(flat["flat"]) is True
    assert bool(varying["flat"]) is False
    assert varying["spread"] == 2.0


def test_build_weights_frame_without_learned_weights():
    frame = build_weights_frame(_items(), {})
    assert list(frame["name"]) == ["pod-restarts:default", "node-pressure"]
    assert frame["learned"].isna().all()
    assert create_weights_plot(frame) is None


def test_build_weights_frame_with_learned_weights():
    frame = build_weights_frame(_items(), {"q1": 0.9, "q2": 0.1})
    row = frame[frame["name"] == "pod-restarts:default"].iloc[0]
    assert row["learned"] == 0.9
    assert round(row["delta"], 4) == 0.15
    assert create_weights_plot(frame) is not None
