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
            "reason": "not scraped",
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


def test_build_contribution_frame_weights_each_query():
    long_df = build_contribution_frame(_df(), _items())
    assert len(long_df) == 4
    first = long_df[
        (long_df["scenario_id"] == "1") & (long_df["name"] == "pod-restarts:default")
    ].iloc[0]
    assert first["raw"] == 2.0
    assert first["contribution"] == 1.5
    assert "etcd-no-leader" not in set(long_df["name"])


def test_build_contribution_frame_skips_mismatched_columns():
    assert build_contribution_frame(_df().drop(columns=["slo_1"]), _items()).empty


def test_build_query_summary_flags_flat_queries():
    summary = build_query_summary(build_contribution_frame(_df(), _items()))
    flat = summary[summary["name"] == "node-pressure"].iloc[0]
    varying = summary[summary["name"] == "pod-restarts:default"].iloc[0]
    assert bool(flat["flat"]) is True
    assert bool(varying["flat"]) is False
    assert varying["spread"] == 2.0


def test_query_colours_match_across_charts():
    long_df = build_contribution_frame(_df(), _items())
    bars = create_contribution_plot(long_df)
    lines = create_query_evolution_plot(long_df, ["node-pressure"])
    assert lines.data[0].name == "node-pressure"
    assert (
        lines.data[0].line.color
        == {t.name: t.marker.color for t in bars.data}["node-pressure"]
    )


def test_build_weights_frame():
    plain = build_weights_frame(_items(), {})
    assert list(plain["name"]) == ["pod-restarts:default", "node-pressure"]
    assert create_weights_plot(plain) is None  # nothing learned yet

    learned = build_weights_frame(_items(), {"q1": 0.9, "q2": 0.1})
    row = learned[learned["name"] == "pod-restarts:default"].iloc[0]
    assert row["learned"] == 0.9
    assert round(row["delta"], 4) == 0.15
    assert create_weights_plot(learned) is not None
