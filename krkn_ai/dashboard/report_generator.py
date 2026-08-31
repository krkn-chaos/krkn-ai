"""
report_generator.py
-------------------
Generates a single self-contained HTML report of the full Krkn-AI dashboard
suitable for CI/CD artifact capture.

Covers every section available in the live dashboard:
  1. Dashboard        — summary, fitness evolution, baseline delta, improvement trend
  2. Fitness          — per-query contributions, query stats, learned weights
  3. Health Checks    — heatmap, success/failure bar, radar-style coverage
  4. Detailed Scenarios — runtime RT chart, success timeline heatmap
  5. Anomaly Detection  — bubble map, anomaly table
  6. Configuration    — structured run configuration and raw YAML
  7. Failed Scenarios   — failed run table
  8. Lineage          — optional origin charts and ancestry records

Public API
----------
generate_html_report(df_all, ...) -> str
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime
from typing import Optional, List

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from krkn_ai.dashboard.tabs.dashboard import (
    create_fitness_evolution_plot,
    create_scenario_distribution_plot,
    create_scenario_fitness_variation_plot,
    create_baseline_delta_plot,
    create_improvement_trend_plot,
)
from krkn_ai.dashboard.tabs.fitness import (
    build_contribution_frame,
    build_query_summary,
    build_rejected_frame,
    build_weights_frame,
    create_contribution_plot,
    create_weights_plot,
    runtime_weights,
)
from krkn_ai.dashboard.data_loader import map_slo_columns
from krkn_ai.dashboard.tabs.health_checks import (
    create_health_checks_heatmap_plot,
    create_success_vs_failure_plot,
    create_health_checks_trend_plot,
    create_resilience_radar_plot,
)
from krkn_ai.dashboard.tabs.detailed_scenarios import (
    create_runtime_telemetry_plot,
    create_success_timeline_plot,
)
from krkn_ai.dashboard.tabs.anomalies import (
    create_anomaly_overview_plot,
    create_anomaly_type_distribution_plot,
    create_service_response_time_heatmap_plot,
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


def _hc_success_failure_bar(df_health: pd.DataFrame) -> str:
    fig = create_success_vs_failure_plot(df_health)
    if fig is None:
        return _na()
    return _fig_html(fig, 330)


def _hc_radar(df_health: pd.DataFrame) -> str:
    fig = create_resilience_radar_plot(df_health)
    if fig is None:
        return _na()
    return _fig_html(fig, 400)


# Detailed Scenarios
def _scen_rt_chart(df_det: pd.DataFrame, global_services: Optional[List[str]] = None) -> str:
    fig = create_runtime_telemetry_plot(df_det)
    if fig is None:
        return _na("No runtime telemetry data recorded.")
    return _fig_html(fig, 400)


def _scen_heatmap(df_det: pd.DataFrame, global_services: Optional[List[str]] = None) -> str:
    fig = create_success_timeline_plot(df_det)
    if fig is None:
        return _na()
    return _fig_html(fig, 350)


# Anomaly Detection
def _anomaly_bubble_map(df_anom: pd.DataFrame, mode: str = "z_score") -> str:
    fig = create_anomaly_overview_plot(df_anom, mode=mode)
    if fig is None:
        return _na("No anomalies detected in this run.")
    return _fig_html(fig, 450)


def _anomaly_table(df_anom: pd.DataFrame, anomaly_mode: str = "z_score") -> str:
    if df_anom is None or df_anom.empty:
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
        if c in df_anom.columns
    ]
    d = df_anom[display_cols].copy()
    if "generation" in d.columns:
        d["generation"] = d["generation"].astype(object)
    return _df_table(d)


# Failed Scenarios
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


# Configuration and Lineage


def _redact_config(value, key=""):
    if str(key).startswith("__"):
        return "***"
    if isinstance(value, dict):
        return {name: _redact_config(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_redact_config(item, key) for item in value]
    return value


def _config_body(config_data, fitness_items=None, health_check_recos=None) -> str:
    if not config_data:
        return _na("Configuration file not found.")

    sections = []
    fitness = config_data.get("fitness_function") or {}
    if fitness_items:
        sections.append(
            _subsec(
                "Fitness Function",
                _df_table(
                    pd.DataFrame(
                        [
                            {
                                "name": item.get("name", "—"),
                                "category": item.get("category") or "—",
                                "type": item.get("type") or "—",
                                "weight": item.get("weight")
                                if item.get("enabled")
                                else None,
                                "status": "in use"
                                if item.get("enabled")
                                else "rejected",
                                "reason": item.get("reason") or "—",
                                "query": item.get("query", ""),
                            }
                            for item in fitness_items
                        ]
                    )
                ),
            )
        )
    elif fitness.get("query"):
        sections.append(
            _subsec(
                "Fitness Function",
                _df_table(
                    pd.DataFrame(
                        [
                            {
                                "mode": "single-query",
                                "type": fitness.get("type", "point"),
                                "query": fitness["query"],
                            }
                        ]
                    )
                ),
            )
        )

    applications = (config_data.get("health_checks") or {}).get("applications") or []
    if applications:
        sections.append(
            _subsec(
                "Health Checks",
                _df_table(pd.DataFrame(_redact_config(applications, "applications"))),
            )
        )
    if health_check_recos:
        sections.append(
            _subsec(
                "Health Checks Discovered but Disabled",
                _df_table(pd.DataFrame(_redact_config(health_check_recos))),
            )
        )

    scenarios = config_data.get("scenario") or {}
    if scenarios:
        sections.append(
            _subsec(
                "Scenarios",
                _df_table(
                    pd.DataFrame(
                        [
                            {
                                "scenario": name,
                                "enabled": bool((value or {}).get("enable")),
                            }
                            for name, value in scenarios.items()
                        ]
                    )
                ),
            )
        )

    components = config_data.get("cluster_components") or {}
    namespaces = components.get("namespaces") or []
    nodes = components.get("nodes") or []
    sections.append(
        _subsec(
            "Cluster Components",
            _cards([("Namespaces", len(namespaces)), ("Nodes", len(nodes))])
            + (
                _df_table(
                    pd.DataFrame(
                        [
                            {
                                "namespace": ns.get("name"),
                                "pods": len(ns.get("pods") or []),
                                "services": len(ns.get("services") or []),
                                "pvcs": len(ns.get("pvcs") or []),
                                "disabled": bool(ns.get("disabled")),
                            }
                            for ns in namespaces
                        ]
                    )
                )
                if namespaces
                else _na("No namespaces recorded.")
            ),
        )
    )

    raw = html.escape(json.dumps(_redact_config(config_data), indent=2, default=str))
    sections.append(
        _subsec("Raw Configuration", f"<pre class='raw-config'>{raw}</pre>")
    )
    return "".join(sections)


def _lineage_body(df_lineage: Optional[pd.DataFrame]) -> str:
    if df_lineage is None or df_lineage.empty:
        return _na("No lineage data available for this run.")

    try:
        from krkn_ai.dashboard.tabs.lineage import _ORIGIN_COLORS, _ORIGIN_LABELS
    except ImportError:
        _ORIGIN_COLORS, _ORIGIN_LABELS = {}, {}

    if "origin" not in df_lineage.columns or not df_lineage["origin"].notna().any():
        return _na("Lineage origin data not recorded for this run.")

    charts = []
    if "origin" in df_lineage.columns:
        origin = df_lineage["origin"].fillna("unknown").astype(str)
        counts = (
            origin.value_counts().rename_axis("origin").reset_index(name="scenarios")
        )
        counts["origin_label"] = counts["origin"].map(
            lambda value: _ORIGIN_LABELS.get(value, value)
        )
        fig = px.pie(
            counts,
            names="origin_label",
            values="scenarios",
            hole=0.45,
            title="Origin Distribution",
            color="origin_label",
            color_discrete_map={
                _ORIGIN_LABELS.get(key, key): value
                for key, value in _ORIGIN_COLORS.items()
            },
        )
        charts.append(_fig_html(fig, 350))

        if "generation" in df_lineage.columns:
            grouped = (
                df_lineage.assign(origin=origin)
                .groupby(["generation", "origin"])
                .size()
                .reset_index(name="scenarios")
            )
            grouped["generation"] = (
                pd.to_numeric(grouped["generation"], errors="coerce") + 1
            )
            grouped["origin_label"] = grouped["origin"].map(
                lambda value: _ORIGIN_LABELS.get(value, value)
            )
            fig = px.bar(
                grouped,
                x="generation",
                y="scenarios",
                color="origin_label",
                title="GA Strategy per Generation",
                barmode="stack",
                color_discrete_map={
                    _ORIGIN_LABELS.get(key, key): value
                    for key, value in _ORIGIN_COLORS.items()
                },
            )
            charts.append(_fig_html(fig, 350))

    columns = [
        column
        for column in [
            "generation",
            "scenario_id",
            "scenario_uuid",
            "origin",
            "fitness_score",
            "parent_ids",
        ]
        if column in df_lineage.columns
    ]
    table = df_lineage[columns].copy() if columns else df_lineage.copy()
    if "generation" in table.columns:
        table["generation"] = pd.to_numeric(table["generation"], errors="coerce") + 1
    if "parent_ids" in table.columns:
        table["parent_ids"] = table["parent_ids"].map(
            lambda value: ", ".join(map(str, value))
            if isinstance(value, (list, tuple))
            else (value or "—")
        )
    return (
        "<div class='two-col'>" + "".join(charts) + "</div>" if charts else ""
    ) + _subsec("Lineage Records", _df_table(table))


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
    df_all: pd.DataFrame,
    run_uuid: Optional[str] = None,
    output_dir: Optional[str] = None,
    delta_baseline: Optional[float] = None,
    delta_prev: Optional[float] = None,
    global_services: Optional[List[str]] = None,
    filtered_scenario_ids: Optional[List] = None,
    anomaly_mode: str = "z_score",
    fitness_items: Optional[List] = None,
    learned_weights: Optional[dict] = None,
    config_data: Optional[dict] = None,
    df_lineage: Optional[pd.DataFrame] = None,
    health_check_recos: Optional[list[dict]] = None,
) -> str:
    """
    Generate a complete HTML report covering every live dashboard section.

    Parameters
    ----------
    df_all               : Raw or baseline-filtered run DataFrame.
    run_uuid             : Run identifier shown in the header.
    output_dir           : Path to the run output directory.
    delta_baseline       : Overall fitness delta vs baseline (fraction, e.g. +0.25).
    delta_prev           : Overall fitness delta vs previous run.
    global_services      : Active service filter list.
    filtered_scenario_ids: Active scenario IDs.
    anomaly_mode          : "z_score" or "pct_deviation" — determines which anomaly detectors fire.
    fitness_items        : Per-query fitness metadata from the run config.
    learned_weights      : Weights the engine learned from the run, keyed by query.
    config_data          : Parsed krkn-ai.yaml configuration.
    df_lineage           : Optional population lineage records.
    health_check_recos   : Health checks discovered but disabled.

    Returns
    -------
    str : Self-contained HTML page.
    """
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    df_results = (
        df_all[df_all["scenario_id"] != 0].copy()
        if (df_all is not None and not df_all.empty and "scenario_id" in df_all.columns)
        else df_all
    )
    if (
        filtered_scenario_ids
        and df_results is not None
        and not df_results.empty
        and "scenario_id" in df_results.columns
    ):
        df_results = df_results[df_results["scenario_id"].isin(filtered_scenario_ids)]

    # Best scenario
    best_row = (
        df_results.sort_values("fitness_score", ascending=False).iloc[0]
        if (
            df_results is not None
            and not df_results.empty
            and "fitness_score" in df_results.columns
        )
        else None
    )
    best_fs = f"{best_row['fitness_score']:.4f}" if best_row is not None else "N/A"
    best_id = f"#{best_row['scenario_id']}" if best_row is not None else "N/A"

    total_scenarios = (
        len(df_results["scenario_id"].unique())
        if (
            df_results is not None
            and not df_results.empty
            and "scenario_id" in df_results.columns
        )
        else 0
    )
    total_generations = (
        int(df_results["generation_id"].max()) + 1
        if (
            df_results is not None
            and not df_results.empty
            and "generation_id" in df_results.columns
        )
        else 0
    )

    # Nav tabs — mirror the live dashboard, including optional lineage.
    tab_defs = [
        ("Dashboard", "tab-dashboard"),
        ("Fitness", "tab-fitness"),
        ("Health Checks", "tab-health"),
        ("Detailed Scenarios", "tab-detailed"),
        ("Anomaly Detection", "tab-anomalies"),
        ("Configuration", "tab-config"),
        ("Failed Scenarios", "tab-failed"),
    ]
    if df_lineage is not None and not df_lineage.empty:
        tab_defs.append(("Lineage", "tab-lineage"))

    # Header
    header = (
        f"<header>"
        f"<h1>Krkn-AI Run Report</h1>"
        f"<p class='meta'>Run ID: {run_uuid or '—'} &nbsp;|&nbsp; Generated: {ts} &nbsp;|&nbsp; Output: {output_dir or '—'}</p>"
        f"</header>"
    )

    # Tab 1: Dashboard
    src = df_all if df_all is not None else pd.DataFrame()
    non_bl = (
        df_all[df_all["scenario_id"] != 0]
        if (df_all is not None and not df_all.empty and "scenario_id" in df_all.columns)
        else pd.DataFrame()
    )
    tab1 = _sec(
        "Executive Summary",
        (
            _cards(
                [
                    ("Total Scenarios", total_scenarios),
                    ("Generations", total_generations),
                    ("Best Fitness Score", best_fs),
                    ("Best Scenario", best_id),
                    (
                        "Δ vs Baseline",
                        f"{delta_baseline:+.1%}"
                        if delta_baseline is not None
                        else "N/A",
                    ),
                    ("Δ vs Prev Run", f"{delta_prev:+.1%}" if delta_prev is not None else "N/A"),
                ]
            )
            + _subsec("Fitness Score Evolution", _dash_fitness_evolution(non_bl))
            + "<hr class='d'/>"
            + _subsec("Baseline vs Best Comparison", _dash_baseline_delta(src))
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
                        f"{sum(runtime_weights(fitness_items or []).values()):.4f}",
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
            _subsec(
                "Response Time Heatmap (per Service / Run)",
                _hc_failure_heatmap(
                    pd.DataFrame()
                ),  # placeholder — caller passes df_health if available
            )
            + "<hr class='d'/>"
            + _subsec(
                "Success vs Failure Counts", _hc_success_failure_bar(pd.DataFrame())
            )
            + "<hr class='d'/>"
            + _subsec("Service Health Radar", _hc_radar(pd.DataFrame()))
        ),
        "tab-health",
    )

    # Detailed Scenarios
    tab3 = _sec(
        "Detailed Scenarios",
        (
            _subsec(
                "Response Time per Scenario",
                _scen_rt_chart(pd.DataFrame(), global_services),
            )
            + "<hr class='d'/>"
            + _subsec(
                "Scenario Success Heatmap",
                _scen_heatmap(pd.DataFrame(), global_services),
            )
        ),
        "tab-detailed",
    )

    # Anomaly Detection
    tab4 = _sec(
        "Anomaly Detection",
        (
            _subsec(
                "Fitness vs Duration Anomaly Map",
                _anomaly_bubble_map(pd.DataFrame()),
            )
            + "<hr class='d'/>"
            + _subsec(
                "Detected Anomalies Summary",
                _anomaly_table(pd.DataFrame(), anomaly_mode=anomaly_mode),
            )
        ),
        "tab-anomalies",
    )

    # Failed Scenarios
    df_failed = (
        df_all[df_all["krkn_failure_score"] > 0]
        if (
            df_all is not None
            and not df_all.empty
            and "krkn_failure_score" in df_all.columns
        )
        else pd.DataFrame()
    )
    tab5 = _sec(
        "Failed Scenarios",
        (
            _subsec("Failure Distribution by Scenario", _failed_bar(df_failed))
            + "<hr class='d'/>"
            + _subsec("Failed Scenario Runs", _df_table(df_failed))
        ),
        "tab-failed",
    )

    tab_config = _sec(
        "Krkn-AI Configuration",
        _config_body(config_data, fitness_items, health_check_recos),
        "tab-config",
    )
    tab_lineage = (
        _sec("Evolutionary Lineage", _lineage_body(df_lineage), "tab-lineage")
        if df_lineage is not None and not df_lineage.empty
        else ""
    )

    body = "\n".join(
        [
            header,
            tab1,
            tab_fit,
            tab2,
            tab3,
            tab4,
            tab_config,
            tab5,
            tab_lineage,
        ]
    )
    return _full_page(body, ts)
