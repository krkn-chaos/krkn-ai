"""
report_generator.py
-------------------
Generates a single self-contained HTML report of the full Krkn-AI dashboard
suitable for CI/CD artifact capture.

Covers all six tabs:
  1. Dashboard        — summary, fitness evolution, baseline delta, improvement trend
  2. Fitness          — per-query contributions, query stats, learned weights
  3. Health Checks    — heatmap, success/failure bar, radar-style coverage
  4. Detailed Scenarios — runtime RT chart, success timeline heatmap
  5. Anomaly Detection  — bubble map, anomaly table
  6. Failed Scenarios   — failed run table

Public API
----------
    generate_html_report(
        df_results, df_health, df_results_all,
        df_details, df_failed,
        global_services, filtered_scenario_ids
    ) -> str
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional, List

import pandas as pd
import plotly.express as px

from krkn_ai.dashboard.tabs.dashboard import (
    create_fitness_evolution_plot,
    create_scenario_distribution_plot,
    create_scenario_fitness_variation_plot,
    create_baseline_delta_plot,
    create_improvement_trend_plot,
)
from krkn_ai.dashboard.tabs.health_checks import (
    create_health_checks_heatmap_plot,
    create_success_vs_failure_plot,
    create_health_checks_trend_plot,
)
from krkn_ai.dashboard.tabs.detailed_scenarios import (
    create_runtime_telemetry_plot,
    create_success_timeline_plot,
)
from krkn_ai.dashboard.tabs.anomalies import (
    create_anomaly_overview_plot,
    create_anomaly_type_distribution_plot,
    create_service_response_time_heatmap_plot,
)
from krkn_ai.dashboard.tabs.fitness import (
    build_contribution_frame,
    build_query_summary,
    build_rejected_frame,
    build_weights_frame,
    create_contribution_plot,
    create_weights_plot,
)
from krkn_ai.dashboard.data_loader import map_slo_columns


# Utilities
def _fig_html(fig, height: int | None = None) -> str:
    if height is not None:
        fig.update_layout(height=height)
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn",
        config={"displayModeBar": False},
    )


def _df_table(df: pd.DataFrame, max_rows: int = 300) -> str:
    if df is None or df.empty:
        return "<p><em>No data available.</em></p>"
    # convert Int64 to object
    df = df.copy()
    for col in df.columns:
        if hasattr(df[col], "dtype") and str(df[col].dtype) == "Int64":
            df[col] = df[col].astype(object)
    return df.head(max_rows).to_html(
        index=False, classes="report-table", border=0, na_rep="—"
    )


def _cards(metrics: list[tuple]) -> str:
    return (
        '<div class="metric-row">'
        + "".join(
            f'<div class="metric-card">'
            f'<span class="metric-val">{v}</span>'
            f'<span class="metric-lbl">{k}</span>'
            f"</div>"
            for k, v in metrics
        )
        + "</div>"
    )


def _sec(title: str, content: str, tab_id: str = "") -> str:
    id_attr = f' id="{tab_id}"' if tab_id else ""
    return (
        f'<section class="report-section"{id_attr}><h2>{title}</h2>{content}</section>'
    )


def _subsec(title: str, content: str) -> str:
    return f'<div class="subsec"><h3>{title}</h3>{content}</div>'


def _na(msg: str = "No data available.") -> str:
    return f"<p class='muted'>{msg}</p>"


# Dashboard
def _dash_fitness_evolution(df: pd.DataFrame) -> str:
    fig = create_fitness_evolution_plot(df)
    if fig is None:
        return _na("No fitness data.")
    return _fig_html(fig, 350)


def _dash_scenario_distribution(df: pd.DataFrame) -> str:
    fig1 = create_scenario_distribution_plot(df)
    fig2 = create_scenario_fitness_variation_plot(df)

    out_html = ""
    if fig1:
        fig1.update_layout(height=350)
        out_html += f"<div class='scenario-dist-item'>{_fig_html(fig1)}</div>"
    if fig2:
        fig2.update_layout(height=350)
        out_html += f"<div class='scenario-dist-item'>{_fig_html(fig2)}</div>"

    if not out_html:
        return _na()

    return f"<div class='scenario-dist-container'>{out_html}</div>"


def _dash_baseline_delta(df_all: pd.DataFrame) -> str:
    fig = create_baseline_delta_plot(df_all)
    if fig is None:
        return _na()
    return _fig_html(fig, 360)


def _dash_improvement_trend(df_all: pd.DataFrame) -> str:
    fig = create_improvement_trend_plot(df_all)
    if fig is None:
        return _na()
    return _fig_html(fig, 330)


def _dash_gen_details(df: pd.DataFrame, fitness_items: Optional[List] = None) -> str:
    if df is None or df.empty:
        return _na()
    slo_map = map_slo_columns(fitness_items or [], df.columns)
    cols = [
        c
        for c in [
            "generation_id",
            "scenario_id",
            "scenario",
            "fitness_score",
            "duration_seconds",
            "health_check_failure_score",
            "health_check_response_time_score",
            "krkn_failure_score",
        ]
        + list(slo_map)
        if c in df.columns
    ]
    tbl = df[cols].copy()
    if "generation_id" in tbl.columns:
        tbl["generation_id"] = tbl["generation_id"] + 1
    tbl = tbl.rename(columns={col: item["name"] for col, item in slo_map.items()})
    return _df_table(tbl.sort_values("fitness_score", ascending=False))


# Fitness
def _fit_contribution(long_df: pd.DataFrame) -> str:
    fig = create_contribution_plot(long_df)
    if fig is None:
        return _na("No per-query fitness scores recorded.")
    return _fig_html(fig, 420)


def _fit_query_table(long_df: pd.DataFrame) -> str:
    summary = build_query_summary(long_df)
    if summary is None or summary.empty:
        return _na()
    return _df_table(summary)


def _fit_weights(weights_df: pd.DataFrame) -> str:
    if weights_df is None or weights_df.empty:
        return _na("No weighted fitness items in this run.")
    fig = create_weights_plot(weights_df)
    table = _df_table(weights_df)
    if fig is None:
        return _na("No learned weights found for this run.") + table
    return _fig_html(fig, 380) + table


def _fit_rejected(fitness_items: Optional[List]) -> str:
    rejected = build_rejected_frame(fitness_items or [])
    if rejected.empty:
        return _na("No queries were rejected.")
    return _df_table(rejected)


# Health Checks
def _hc_failure_heatmap(df_health: pd.DataFrame) -> str:
    fig = create_health_checks_heatmap_plot(df_health)
    if fig is None:
        return _na()
    return _fig_html(fig, 400)


def _hc_success_bar(df_health: pd.DataFrame) -> str:
    fig = create_success_vs_failure_plot(df_health)
    if fig is None:
        return _na()
    return _fig_html(fig, 330)


def _hc_rt_trend(df_health: pd.DataFrame) -> str:
    fig = create_health_checks_trend_plot(df_health)
    if fig is None:
        return _na()
    return _fig_html(fig, 330)


def _hc_worst_table(df_health: pd.DataFrame) -> str:
    if df_health is None or df_health.empty:
        return _na()
    df = df_health.copy()
    if "failure_rate" not in df.columns:
        df["total"] = df.get("failure_count", 0) + df.get("success_count", 0)
        df["failure_rate"] = df.apply(
            lambda r: r["failure_count"] / r["total"] if r["total"] > 0 else 0.0, axis=1
        )
    cols = [
        c
        for c in [
            "component_name",
            "scenario_id",
            "average_response_time",
            "max_response_time",
            "failure_count",
            "success_count",
            "failure_rate",
        ]
        if c in df.columns
    ]
    return _df_table(df[cols].sort_values("failure_rate", ascending=False))


# Detailed Scenarios
def _det_rt_chart(df_det: pd.DataFrame) -> str:
    fig = create_runtime_telemetry_plot(df_det)
    if fig is None:
        return _na("No YAML telemetry data.")
    return _fig_html(fig, 400)


def _det_success_timeline(df_det: pd.DataFrame) -> str:
    fig = create_success_timeline_plot(df_det)
    if fig is None:
        return _na()
    return _fig_html(fig, 350)


def _det_svc_rt_heatmap(df_det: pd.DataFrame) -> str:
    fig = create_service_response_time_heatmap_plot(df_det)
    if fig is None:
        return _na()
    return _fig_html(fig, 400)


# Anomaly Detection
def _run_detectors(
    src, df_health, df_det, global_services, anomaly_mode: str = "z_score"
) -> pd.DataFrame:
    try:
        from krkn_ai.dashboard.tabs.anomalies import (  # noqa: PLC0415
            detect_fitness_iqr_anomalies,
            detect_duration_anomalies,
            detect_hc_failure_surge,
            detect_fitness_regression,
            detect_service_failure_spikes,
            detect_krkn_failure_score_anomalies,
            detect_hc_response_time_anomalies,
            detect_service_response_time_spikes,
            _extract_baseline,
        )
    except ImportError:
        return pd.DataFrame()
    if src is None or src.empty:
        return pd.DataFrame()
    baseline = _extract_baseline(src)
    parts = [
        detect_fitness_iqr_anomalies(
            src, baseline.get("fitness_score"), mode=anomaly_mode
        ),
        detect_duration_anomalies(
            src, baseline.get("duration_seconds"), mode=anomaly_mode
        ),
        detect_hc_failure_surge(
            src, baseline.get("health_check_failure_score"), mode=anomaly_mode
        ),
        detect_fitness_regression(src),
        detect_service_failure_spikes(df_health, mode=anomaly_mode),
        detect_krkn_failure_score_anomalies(src),
        detect_hc_response_time_anomalies(
            src, baseline.get("health_check_response_time_score"), mode=anomaly_mode
        ),
        detect_service_response_time_spikes(df_det, global_services, mode=anomaly_mode),
    ]
    non_empty = [p.dropna(axis=1, how="all") for p in parts if not p.empty]
    if not non_empty:
        return pd.DataFrame()
    m = pd.concat(non_empty, ignore_index=True)
    if "scenario_id" in m.columns:
        m["scenario_id"] = m["scenario_id"].astype(str)
    if "generation" in m.columns:
        m["generation"] = pd.to_numeric(m["generation"], errors="coerce").astype(
            "Int64"
        )
    return m


def _anom_bubble(df: pd.DataFrame, mode: str = "z_score") -> str:
    fig = create_anomaly_overview_plot(df, mode=mode)
    if fig is None:
        return _na("No anomalies detected.")
    return _fig_html(fig, 450)


def _anom_type_bar(df: pd.DataFrame) -> str:
    fig = create_anomaly_type_distribution_plot(df)
    if fig is None:
        return _na()
    return _fig_html(fig, 350)


def _anom_table(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return _na("No anomalies detected.")
    display_cols = [
        c
        for c in [
            "severity",
            "anomaly_type",
            "scenario_id",
            "scenario",
            "generation",
            "value",
            "z_score",
            "detail",
        ]
        if c in df.columns
    ]
    d = df[display_cols].copy()
    if "generation" in d.columns:
        d["generation"] = d["generation"].astype(object)
    return _df_table(d)


# Failed Scenarios
def _failed_table(df_failed: pd.DataFrame) -> str:
    if df_failed is None or df_failed.empty:
        return "<p class='muted good'>No failed scenarios detected.</p>"
    cols = [
        c
        for c in [
            "generation_id",
            "scenario_id",
            "scenario",
            "fitness_score",
            "krkn_failure_score",
            "duration_seconds",
            "health_check_failure_score",
        ]
        if c in df_failed.columns
    ]
    d = df_failed[cols].copy()
    if "generation_id" in d.columns:
        d["generation_id"] = d["generation_id"] + 1
    return _df_table(
        d.sort_values("krkn_failure_score") if "krkn_failure_score" in d.columns else d
    )


def _failed_bar(df_failed: pd.DataFrame) -> str:
    if df_failed is None or df_failed.empty:
        return ""
    if (
        "scenario" not in df_failed.columns
        or "krkn_failure_score" not in df_failed.columns
    ):
        return ""
    fig = px.bar(
        df_failed,
        x="scenario",
        y="krkn_failure_score",
        color="krkn_failure_score",
        color_continuous_scale=[[0, "#ef4444"], [1, "#7f1d1d"]],
        title="Failed Scenarios — Krkn Failure Score",
    )
    fig.update_layout(
        xaxis_tickangle=-30, xaxis_title="Scenario", yaxis_title="Krkn Failure Score"
    )
    return _fig_html(fig, 320)


# HTML Template
_PLOTLY_CDN = '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'


def _get_css() -> str:
    css_path = os.path.join(os.path.dirname(__file__), "report.css")
    try:
        with open(css_path, "r", encoding="utf-8") as f:
            return f"<style>{f.read()}</style>"
    except Exception:
        return "<style></style>"


def _nav_bar(tabs: list[tuple[str, str]]) -> str:
    links = "".join(f'<a href="#{tid}">{label}</a>' for label, tid in tabs)
    return f'<nav class="nav">{links}</nav>'


def _full_page(body: str, ts: str) -> str:
    return (
        f"<!DOCTYPE html><html lang='en'><head>"
        f"<meta charset='UTF-8'/>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'/>"
        f"<title>Krkn-AI Report: {ts}</title>"
        f"{_PLOTLY_CDN}{_get_css()}</head><body>{body}</body></html>"
    )


# Public API
def generate_html_report(
    df_results: pd.DataFrame,
    df_health: Optional[pd.DataFrame] = None,
    df_results_all: Optional[pd.DataFrame] = None,
    df_details: Optional[pd.DataFrame] = None,
    df_failed: Optional[pd.DataFrame] = None,
    global_services: Optional[List[str]] = None,
    filtered_scenario_ids: Optional[List] = None,
    anomaly_mode: str = "z_score",
    fitness_items: Optional[List] = None,
    learned_weights: Optional[dict] = None,
) -> str:
    """
    Generate a complete self-contained HTML report covering all five dashboard tabs.

    Parameters
    ----------
    df_results           : Filtered scenario results.
    df_health            : health_check_report.csv data.
    df_results_all       : Unfiltered results including baseline row.
    df_details           : Per-request YAML telemetry.
    df_failed            : Rows where krkn_failure_score < 0.
    global_services      : Active service filter list.
    filtered_scenario_ids: Active scenario IDs.
    anomaly_mode          : "z_score" or "pct_deviation" — determines which anomaly detectors fire.
    fitness_items        : Per-query fitness metadata from the run config.
    learned_weights      : Weights the engine learned from the run, keyed by query.

    Returns
    -------
    str — complete HTML document.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    src = df_results_all if df_results_all is not None else df_results

    # Filter df_details
    df_det: Optional[pd.DataFrame] = None
    if df_details is not None and not df_details.empty:
        df_det = df_details.copy()
        df_det["scenario_id"] = df_det["scenario_id"].astype(str)
        if filtered_scenario_ids:
            str_ids = [str(x) for x in filtered_scenario_ids] + ["baseline"]
            df_det = df_det[df_det["scenario_id"].isin(str_ids)]
        if global_services:
            df_det = df_det[df_det["service"].isin(global_services)]

    # Summary metrics
    non_bl = (
        src[src["scenario_id"].astype(str) != "baseline"]
        if src is not None and not src.empty
        else pd.DataFrame()
    )
    gens = (
        int(non_bl["generation_id"].max() + 1)
        if "generation_id" in non_bl.columns and not non_bl.empty
        else 0
    )
    n_sc = len(non_bl)
    best_fit = (
        f"{non_bl['fitness_score'].max():.1f}%"
        if "fitness_score" in non_bl.columns and not non_bl.empty
        else "—"
    )
    avg_fit = (
        f"{non_bl['fitness_score'].mean():.1f}%"
        if "fitness_score" in non_bl.columns and not non_bl.empty
        else "—"
    )
    svc_filter = ", ".join(global_services) if global_services else "All"
    n_failed = len(df_failed) if df_failed is not None else 0

    # Run anomaly detectors
    all_anomalies = _run_detectors(
        src, df_health, df_det, global_services, anomaly_mode
    )
    n_anom = len(all_anomalies)
    n_high = (
        int((all_anomalies["severity"] == "High").sum())
        if not all_anomalies.empty
        else 0
    )

    # Nav tabs
    tab_defs = [
        ("Dashboard", "tab-dashboard"),
        ("Fitness", "tab-fitness"),
        ("Health Checks", "tab-health"),
        ("Detailed Scenarios", "tab-detailed"),
        ("Anomaly Detection", "tab-anomalies"),
        ("Failed Scenarios", "tab-failed"),
    ]

    # Header
    header = (
        f"<h1>Krkn-AI Dashboard Report</h1>"
        f"<p class='meta'>Generated: {ts}"
        f" &nbsp;|&nbsp; Services: {svc_filter}"
        f" &nbsp;|&nbsp; Generations: {gens}"
        f" &nbsp;|&nbsp; Scenarios: {n_sc}"
        f" &nbsp;|&nbsp; Anomalies: {n_anom} ({n_high} High)"
        f" &nbsp;|&nbsp; Failed: {n_failed}"
        f"</p>" + _nav_bar(tab_defs)
    )

    # Dashboard
    summary_cards = _cards(
        [
            ("Generations", gens),
            ("Scenarios", n_sc),
            ("Best Fitness", best_fit),
            ("Avg Fitness", avg_fit),
            ("Failed Scenarios", n_failed),
        ]
    )
    tab1 = _sec(
        "Dashboard",
        (
            summary_cards
            + _subsec("Fitness Evolution", _dash_fitness_evolution(non_bl))
            + "<hr class='d'/>"
            + _subsec("Scenario Distribution", _dash_scenario_distribution(non_bl))
            + "<hr class='d'/>"
            + _subsec("Score Delta vs Baseline", _dash_baseline_delta(src))
            + "<hr class='d'/>"
            + _subsec(
                "Fitness Improvement Trend vs Baseline", _dash_improvement_trend(src)
            )
            + "<hr class='d'/>"
            + _subsec(
                "Generation & Scenario Details",
                _dash_gen_details(df_results, fitness_items),
            )
        ),
        "tab-dashboard",
    )

    # Fitness
    long_df = build_contribution_frame(non_bl, fitness_items or [])
    weights_df = build_weights_frame(fitness_items or [], learned_weights)
    enabled_items = [item for item in (fitness_items or []) if item["enabled"]]
    tab_fit = _sec(
        "Fitness",
        (
            _cards(
                [
                    ("Queries In Use", len(enabled_items)),
                    (
                        "Queries Rejected",
                        len(fitness_items or []) - len(enabled_items),
                    ),
                    (
                        "Total Weight",
                        f"{sum(item['weight'] for item in enabled_items):.4f}",
                    ),
                ]
            )
            + _subsec("Fitness Contribution by Query", _fit_contribution(long_df))
            + "<hr class='d'/>"
            + _subsec("Query Statistics", _fit_query_table(long_df))
            + "<hr class='d'/>"
            + _subsec("Configured vs Learned Weights", _fit_weights(weights_df))
            + "<hr class='d'/>"
            + _subsec("Queries Discover Rejected", _fit_rejected(fitness_items))
        ),
        "tab-fitness",
    )

    # Health Checks
    tab2 = _sec(
        "Health Checks",
        (
            _subsec("Service Failure Rate Heatmap", _hc_failure_heatmap(df_health))
            + "<hr class='d'/>"
            + '<div class="two-col">'
            + "<div>"
            + _subsec("Success vs Failure Counts", _hc_success_bar(df_health))
            + "</div>"
            + "<div>"
            + _subsec("Avg Response Time Trend", _hc_rt_trend(df_health))
            + "</div>"
            + "</div>"
            + "<hr class='d'/>"
            + _subsec("All Health Check Data", _hc_worst_table(df_health))
        ),
        "tab-health",
    )

    # Detailed Scenarios
    tab3 = _sec(
        "Detailed Scenarios",
        (
            _subsec(
                "Runtime Telemetry: Response Time vs Execution Time",
                _det_rt_chart(df_det),
            )
            + "<hr class='d'/>"
            + _subsec(
                "Service Response Time Heatmap (Scenario × Service)",
                _det_svc_rt_heatmap(df_det),
            )
            + "<hr class='d'/>"
            + _subsec("Success Timeline per Service", _det_success_timeline(df_det))
        ),
        "tab-detailed",
    )

    # Anomaly Detection
    if not all_anomalies.empty:
        an_high = int((all_anomalies["severity"] == "High").sum())
        an_medium = int((all_anomalies["severity"] == "Medium").sum())
        an_low = int((all_anomalies["severity"] == "Low").sum())
        anom_cards = _cards(
            [
                ("Total Anomalies", n_anom),
                ("High Severity", an_high),
                ("Medium Severity", an_medium),
                ("Low Severity", an_low),
            ]
        )
        anom_body = (
            anom_cards
            + '<div class="two-col">'
            + "<div>"
            + _anom_bubble(all_anomalies, mode=anomaly_mode)
            + "</div>"
            + "<div>"
            + _anom_type_bar(all_anomalies)
            + "</div>"
            + "</div>"
            + "<hr class='d'/>"
            + _subsec("All Detected Anomalies", _anom_table(all_anomalies))
        )
    else:
        anom_body = "<p class='muted good'>No anomalies detected.</p>"

    mode_badge = (
        "Z-Score (statistical)"
        if anomaly_mode == "z_score"
        else "% Deviation from Baseline"
    )
    tab4 = _sec(
        "Anomaly Detection",
        f"<p class='muted'>Detection mode: <strong>{mode_badge}</strong></p>"
        + anom_body,
        "tab-anomalies",
    )

    # Failed Scenarios
    tab5 = _sec(
        "Failed Scenarios",
        (
            _subsec("Failed Scenario Summary", _failed_bar(df_failed))
            + "<hr class='d'/>"
            + _subsec(
                "Failed Scenario Details (krkn_failure_score < 0)",
                _failed_table(df_failed),
            )
        ),
        "tab-failed",
    )

    body = "\n".join([header, tab1, tab_fit, tab2, tab3, tab4, tab5])
    return _full_page(body, ts)
