"""
Anomaly Detection Tab for Krkn-AI Dashboard.

Algorithms:
  1. IQR-based outlier detection on fitness_score.
  2. Z-score on duration_seconds vs baseline duration.
  3. Rule-based health-check failure surge detection.
  4. Service-level failure-rate spike (health_check_report.csv).
  5. health_check_response_time_score anomaly detection.
"""

from __future__ import annotations

from typing import Optional, List

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st


# Detection mode constants
MODE_ZSCORE = "z_score"
MODE_PCT = "pct_deviation"

# Constants / colour maps
ANOMALY_COLORS = {
    "Low Fitness (IQR)": "#ef4444",
    "High Fitness (IQR)": "#22c55e",
    "Duration (Execution Time) Anomaly (Z-score)": "#f97316",
    "Health Check Failure Surge": "#eab308",
    "Fitness Regression": "#8b5cf6",
    "Service Failure Rate Spike": "#06b6d4",
    "Krkn Failure Score Spike": "#ec4899",
    "Health Check Response Time (Latency) Anomaly": "#a78bfa",
    "Service Response Time (Latency) Spike": "#fb923c",
}

SEVERITY_ORDER = ["High", "Medium", "Low"]
SEVERITY_COLORS = {"High": "#ef4444", "Medium": "#f97316", "Low": "#eab308"}


@st.cache_data
def load_anomaly_config() -> dict:
    import os

    config_path = os.path.join(os.path.dirname(__file__), "..", "anomaly_config.yaml")
    if os.path.exists(config_path):
        try:
            import yaml

            with open(config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            pass
        except Exception as e:
            st.warning(f"Error loading anomaly_config.yaml: {e}")
    return {}


def get_anomaly_config() -> dict:
    return load_anomaly_config()


# used maths helpers
def _iqr_bounds(series: pd.Series, k: float = None):
    if k is None:
        k = get_anomaly_config().get("iqr_k", 1.5)
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def _zscore(value: float, mean: float, std: float) -> float:
    return 0.0 if std == 0 else (value - mean) / std


def _severity(z: float) -> str:
    az = abs(z)
    cfg = get_anomaly_config().get("severity", {})
    if az >= cfg.get("high_z", 2.5):
        return "High"
    if az >= cfg.get("medium_z", 1.5):
        return "Medium"
    return "Low"


def _severity_pct(pct: float) -> str:
    apct = abs(pct)
    cfg = get_anomaly_config().get("severity", {})
    if apct >= cfg.get("high_pct", 60.0):
        return "High"
    if apct >= cfg.get("medium_pct", 30.0):
        return "Medium"
    return "Low"


def _safe_float(row, col):
    try:
        v = row[col]
        return float(v) if not pd.isna(v) else None
    except Exception:
        return None


# Anomaly detectors
def detect_fitness_iqr_anomalies(
    df: pd.DataFrame,
    baseline_fitness: Optional[float] = None,
    mode: str = MODE_ZSCORE,
) -> pd.DataFrame:
    if df is None or df.empty or "fitness_score" not in df.columns:
        return pd.DataFrame()
    working = df[df["scenario_id"].astype(str) != "baseline"].copy()
    if working.empty:
        return pd.DataFrame()
    lower, upper = _iqr_bounds(working["fitness_score"])
    mean_fs = working["fitness_score"].mean()
    std_fs = working["fitness_score"].std(ddof=0)
    anomalies = []
    for _, row in working.iterrows():
        fs = float(row["fitness_score"])
        reasons = []
        # IQR check — applies in both modes
        if fs < lower:
            reasons.append(f"Fitness {fs:.3f} below IQR lower fence {lower:.3f}")
        if fs > upper:
            reasons.append(f"Fitness {fs:.3f} above IQR upper fence {upper:.3f}")
        # Baseline check — only in pct mode
        if mode == MODE_PCT and baseline_fitness is not None:
            if fs < baseline_fitness:
                pct = ((baseline_fitness - fs) / max(baseline_fitness, 1e-6)) * 100
                reasons.append(
                    f"Fitness {fs:.3f} is {pct:.1f}% below baseline {baseline_fitness:.3f}"
                )
        elif (
            mode == MODE_ZSCORE
            and baseline_fitness is not None
            and fs < baseline_fitness
        ):
            reasons.append(f"Fitness {fs:.3f} below baseline {baseline_fitness:.3f}")
        if not reasons:
            continue
        atype = (
            "Low Fitness (IQR)"
            if fs < lower or (baseline_fitness is not None and fs < baseline_fitness)
            else "High Fitness (IQR)"
        )
        z = _zscore(fs, mean_fs, std_fs)
        pct_bl = (
            ((baseline_fitness - fs) / max(baseline_fitness, 1e-6) * 100)
            if baseline_fitness
            else 0.0
        )
        severity = _severity_pct(pct_bl) if mode == MODE_PCT else _severity(z)
        anomalies.append(
            {
                "scenario_id": row.get("scenario_id", "?"),
                "scenario": row.get("scenario", "?"),
                "generation": int(row["generation_id"]) + 1
                if "generation_id" in row and not pd.isna(row["generation_id"])
                else None,
                "anomaly_type": atype,
                "value": fs,
                "threshold": lower if fs < lower else upper,
                "baseline_ref": baseline_fitness,
                "z_score": round(z, 3),
                "severity": severity,
                "detail": " | ".join(reasons),
            }
        )
    return pd.DataFrame(anomalies)


def detect_duration_anomalies(
    df: pd.DataFrame,
    baseline_duration: Optional[float] = None,
    mode: str = MODE_ZSCORE,
) -> pd.DataFrame:
    if df is None or df.empty or "duration_seconds" not in df.columns:
        return pd.DataFrame()
    working = df[df["scenario_id"].astype(str) != "baseline"].copy()
    if working.empty:
        return pd.DataFrame()

    cfg = get_anomaly_config().get("duration", {})

    if baseline_duration is not None and baseline_duration > 0:
        diffs = working["duration_seconds"] - baseline_duration
        std_d = float(np.sqrt((diffs**2).mean()))
        ref = baseline_duration
        ref_label = f"baseline {baseline_duration:.1f}s"
    else:
        ref = working["duration_seconds"].mean()
        std_d = working["duration_seconds"].std(ddof=0)
        ref_label = f"mean {ref:.1f}s"

    anomalies = []
    for _, row in working.iterrows():
        d = float(row["duration_seconds"])
        z = _zscore(d, ref, std_d)
        reasons = []

        if mode == MODE_ZSCORE:
            if abs(z) >= cfg.get("z_threshold", 1.5):
                direction = "longer" if d > ref else "shorter"
                reasons.append(
                    f"Duration {d:.1f}s significantly {direction} than {ref_label} (z={z:+.2f})"
                )
        else:  # MODE_PCT
            if baseline_duration is not None and baseline_duration > 0:
                pct = ((d - baseline_duration) / baseline_duration) * 100
                if abs(pct) >= cfg.get("baseline_pct", 30.0):
                    reasons.append(
                        f"{pct:+.1f}% vs baseline duration {baseline_duration:.1f}s"
                    )

        if not reasons:
            continue

        pct_for_sev = ((d - ref) / max(ref, 1e-6)) * 100 if mode == MODE_PCT else 0.0
        severity = _severity_pct(pct_for_sev) if mode == MODE_PCT else _severity(z)
        anomalies.append(
            {
                "scenario_id": row.get("scenario_id", "?"),
                "scenario": row.get("scenario", "?"),
                "generation": int(row["generation_id"]) + 1
                if "generation_id" in row and not pd.isna(row["generation_id"])
                else None,
                "anomaly_type": "Duration (Execution Time) Anomaly (Z-score)",
                "value": d,
                "threshold": ref,
                "baseline_ref": baseline_duration,
                "z_score": round(z, 3),
                "severity": severity,
                "detail": " | ".join(reasons),
            }
        )
    return pd.DataFrame(anomalies)


def detect_hc_failure_surge(
    df: pd.DataFrame,
    baseline_hc_failure: Optional[float] = None,
    mode: str = MODE_ZSCORE,
) -> pd.DataFrame:
    if df is None or df.empty or "health_check_failure_score" not in df.columns:
        return pd.DataFrame()
    working = df[df["scenario_id"].astype(str) != "baseline"].copy()
    if working.empty:
        return pd.DataFrame()
    _, upper = _iqr_bounds(working["health_check_failure_score"])
    mean_hc = working["health_check_failure_score"].mean()
    std_hc = working["health_check_failure_score"].std(ddof=0)
    anomalies = []
    cfg = get_anomaly_config().get("hc_failure", {})
    for _, row in working.iterrows():
        hcf = float(row["health_check_failure_score"])
        z = _zscore(hcf, mean_hc, std_hc)
        reasons = []
        if mode == MODE_ZSCORE:
            if hcf > upper:
                reasons.append(
                    f"Health Check Failure score {hcf:.3f} above IQR upper fence {upper:.3f}"
                )
        else:  # MODE_PCT
            if baseline_hc_failure is not None and baseline_hc_failure > 0:
                pct = ((hcf - baseline_hc_failure) / baseline_hc_failure) * 100
                if abs(pct) >= cfg.get("baseline_pct", 30.0):
                    direction = "above" if pct > 0 else "below"
                    reasons.append(
                        f"{pct:+.1f}% {direction} baseline Health Check failure score {baseline_hc_failure:.3f}"
                    )
        if not reasons:
            continue
        pct_sev = (
            (hcf - (baseline_hc_failure or mean_hc))
            / max(baseline_hc_failure or mean_hc, 1e-6)
        ) * 100
        severity = _severity_pct(pct_sev) if mode == MODE_PCT else _severity(z)
        anomalies.append(
            {
                "scenario_id": row.get("scenario_id", "?"),
                "scenario": row.get("scenario", "?"),
                "generation": int(row["generation_id"]) + 1
                if "generation_id" in row and not pd.isna(row["generation_id"])
                else None,
                "anomaly_type": "Health Check Failure Surge",
                "value": hcf,
                "threshold": upper,
                "baseline_ref": baseline_hc_failure,
                "z_score": round(z, 3),
                "severity": severity,
                "detail": " | ".join(reasons),
            }
        )
    return pd.DataFrame(anomalies)


def detect_fitness_regression(df: pd.DataFrame) -> pd.DataFrame:
    if (
        df is None
        or df.empty
        or "generation_id" not in df.columns
        or "fitness_score" not in df.columns
    ):
        return pd.DataFrame()
    working = df[df["scenario_id"].astype(str) != "baseline"].copy()
    if working.empty:
        return pd.DataFrame()
    gen_best = working.groupby("generation_id")["fitness_score"].max().sort_index()
    anomalies = []
    prev_gen = prev_best = None
    cfg = get_anomaly_config().get("fitness_regression", {})
    for gen_id, best_fs in gen_best.items():
        if prev_best is not None and prev_gen is not None and best_fs < prev_best:
            drop_pct = ((prev_best - best_fs) / max(prev_best, 1e-6)) * 100
            z = -drop_pct / cfg.get("z_div", 10.0)
            severity = (
                "High"
                if drop_pct > cfg.get("high_drop_pct", 20.0)
                else "Medium"
                if drop_pct > cfg.get("medium_drop_pct", 10.0)
                else "Low"
            )
            anomalies.append(
                {
                    "scenario_id": int(gen_id) + 1,
                    "scenario": f"Generation {int(gen_id) + 1}",
                    "generation": int(gen_id) + 1,
                    "anomaly_type": "Fitness Regression",
                    "value": best_fs,
                    "threshold": prev_best,
                    "baseline_ref": None,
                    "z_score": round(z, 3),
                    "severity": severity,
                    "detail": (
                        f"Best fitness dropped from Gen {int(prev_gen) + 1} ({prev_best:.3f})"
                        f" to Gen {int(gen_id) + 1} ({best_fs:.3f})"
                        f" — {drop_pct:.1f}% regression"
                    ),
                }
            )
        prev_gen = gen_id
        prev_best = best_fs
    return pd.DataFrame(anomalies)


def detect_service_failure_spikes(
    df_health: pd.DataFrame,
    baseline_scenario_ids: list | None = None,
    mode: str = MODE_ZSCORE,
) -> pd.DataFrame:
    if df_health is None or df_health.empty:
        return pd.DataFrame()
    required = {"scenario_id", "component_name", "failure_count", "success_count"}
    if not required.issubset(df_health.columns):
        return pd.DataFrame()
    df = df_health.copy()
    df["scenario_id"] = df["scenario_id"].astype(str)
    df["total"] = df["failure_count"] + df["success_count"]
    df["failure_rate"] = df.apply(
        lambda r: r["failure_count"] / r["total"] if r["total"] > 0 else 0.0, axis=1
    )
    baseline_ids = [str(b) for b in (baseline_scenario_ids or ["baseline"])]
    bl_rates = (
        df[df["scenario_id"].isin(baseline_ids)]
        .groupby("component_name")["failure_rate"]
        .mean()
        .to_dict()
    )
    non_bl = df[~df["scenario_id"].isin(baseline_ids)]
    if non_bl.empty:
        return pd.DataFrame()
    svc_stats = (
        non_bl.groupby("component_name")["failure_rate"].agg(["mean", "std"]).fillna(0)
    )
    anomalies = []
    for _, row in non_bl.iterrows():
        svc = row["component_name"]
        fr = row["failure_rate"]
        bl_fr = bl_rates.get(svc)
        stats = svc_stats.loc[svc] if svc in svc_stats.index else None
        z = (
            _zscore(fr, stats["mean"], stats["std"])
            if (stats is not None and stats["std"] > 0)
            else 0.0
        )
        reasons = []
        if mode == MODE_ZSCORE:
            if abs(z) >= 1.5:
                reasons.append(
                    f"Failure rate {fr:.1%} — z={z:+.2f} vs service distribution"
                )
        else:  # MODE_PCT
            if bl_fr is not None and bl_fr > 0:
                pct = ((fr - bl_fr) / bl_fr) * 100
                if abs(pct) >= 30.0:
                    direction = "above" if pct > 0 else "below"
                    reasons.append(
                        f"{pct:+.1f}% {direction} baseline failure rate {bl_fr:.1%}"
                    )
        if not reasons:
            continue
        pct_sev = ((fr - (bl_fr or 0)) / max(bl_fr or 1e-6, 1e-6)) * 100
        severity = (
            _severity_pct(pct_sev)
            if mode == MODE_PCT
            else (_severity(z) if abs(z) >= 1.5 else "Low")
        )
        anomalies.append(
            {
                "scenario_id": row["scenario_id"],
                "scenario": svc,
                "generation": None,
                "anomaly_type": "Service Failure Rate Spike",
                "value": round(fr, 4),
                "threshold": bl_fr if bl_fr is not None else float("nan"),
                "baseline_ref": bl_fr,
                "z_score": round(z, 3),
                "severity": severity,
                "detail": " | ".join(reasons),
            }
        )
    return pd.DataFrame(anomalies)


def detect_krkn_failure_score_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Flag scenarios with krkn_failure_score > 0 or as IQR outlier."""
    if df is None or df.empty or "krkn_failure_score" not in df.columns:
        return pd.DataFrame()
    working = df[df["scenario_id"].astype(str) != "baseline"].copy()
    working = working[working["krkn_failure_score"].notna()]
    nonzero = working[working["krkn_failure_score"] > 0]
    if nonzero.empty:
        return pd.DataFrame()
    mean_k = working["krkn_failure_score"].mean()
    std_k = working["krkn_failure_score"].std(ddof=0)
    _, upper = _iqr_bounds(working["krkn_failure_score"])
    anomalies = []
    for _, row in nonzero.iterrows():
        kf = float(row["krkn_failure_score"])
        z = _zscore(kf, mean_k, std_k)
        reasons = [f"krkn_failure_score = {kf:.3f} (non-zero → krkn engine error)"]
        if kf > upper:
            reasons.append(f"Above IQR upper fence {upper:.3f}")
        anomalies.append(
            {
                "scenario_id": row.get("scenario_id", "?"),
                "scenario": row.get("scenario", "?"),
                "generation": int(row["generation_id"]) + 1
                if "generation_id" in row and not pd.isna(row["generation_id"])
                else None,
                "anomaly_type": "Krkn Failure Score Spike",
                "value": kf,
                "threshold": 0.0,
                "baseline_ref": None,
                "z_score": round(z, 3),
                "severity": "High" if kf > upper else "Medium",
                "detail": " | ".join(reasons),
            }
        )
    return pd.DataFrame(anomalies)


def detect_hc_response_time_anomalies(
    df: pd.DataFrame,
    baseline_hc_rt: Optional[float] = None,
    mode: str = MODE_ZSCORE,
) -> pd.DataFrame:
    """Flag scenarios with unusually high health_check_response_time_score."""
    col = "health_check_response_time_score"
    if df is None or df.empty or col not in df.columns:
        return pd.DataFrame()
    working = df[df["scenario_id"].astype(str) != "baseline"].copy()
    if working.empty or len(working) < 2:
        return pd.DataFrame()
    mean_rt = working[col].mean()
    std_rt = working[col].std(ddof=0)
    _, upper = _iqr_bounds(working[col])
    anomalies = []
    cfg = get_anomaly_config().get("hc_response_time", {})
    for _, row in working.iterrows():
        rt = float(row[col])
        z = _zscore(rt, mean_rt, std_rt)
        reasons = []
        if mode == MODE_ZSCORE:
            if rt > upper:
                reasons.append(
                    f"Health Check Response Time score {rt:.3f} above IQR upper fence {upper:.3f}"
                )
            if abs(z) >= cfg.get("z_threshold", 1.5):
                reasons.append(f"Z-score {z:+.2f} vs run distribution")
        else:  # MODE_PCT
            if baseline_hc_rt is not None and baseline_hc_rt > 0:
                pct = ((rt - baseline_hc_rt) / baseline_hc_rt) * 100
                if abs(pct) >= cfg.get("baseline_pct", 30.0):
                    direction = "above" if pct > 0 else "below"
                    reasons.append(
                        f"{pct:+.1f}% {direction} baseline Health Check RT score {baseline_hc_rt:.3f}"
                    )
        if not reasons:
            continue
        pct_sev = (
            (rt - (baseline_hc_rt or mean_rt)) / max(baseline_hc_rt or mean_rt, 1e-6)
        ) * 100
        severity = _severity_pct(pct_sev) if mode == MODE_PCT else _severity(z)
        anomalies.append(
            {
                "scenario_id": row.get("scenario_id", "?"),
                "scenario": row.get("scenario", "?"),
                "generation": int(row["generation_id"]) + 1
                if "generation_id" in row and not pd.isna(row["generation_id"])
                else None,
                "anomaly_type": "Health Check Response Time (Latency) Anomaly",
                "value": rt,
                "threshold": upper,
                "baseline_ref": baseline_hc_rt,
                "z_score": round(z, 3),
                "severity": severity,
                "detail": " | ".join(reasons),
            }
        )
    return pd.DataFrame(anomalies)


def detect_service_response_time_spikes(
    df_details: pd.DataFrame,
    global_services: Optional[List[str]] = None,
    mode: str = MODE_ZSCORE,
) -> pd.DataFrame:
    """
    Detect per-service max/avg response time anomalies across scenarios using
    the YAML telemetry (df_details from load_detailed_scenarios_data).
    Baseline scenario_id is 'baseline'.
    """
    if df_details is None or df_details.empty:
        return pd.DataFrame()
    required = {"scenario_id", "service", "response_time"}
    if not required.issubset(df_details.columns):
        return pd.DataFrame()

    df = df_details.copy()
    df["scenario_id"] = df["scenario_id"].astype(str)
    if global_services:
        df = df[df["service"].isin(global_services)]
    if df.empty:
        return pd.DataFrame()

    agg = (
        df.groupby(["scenario_id", "service"])["response_time"]
        .agg(mean_rt="mean", max_rt="max", p95_rt=lambda x: x.quantile(0.95))
        .reset_index()
    )

    baseline_agg = agg[agg["scenario_id"] == "baseline"].set_index("service")
    non_bl = agg[agg["scenario_id"] != "baseline"].copy()
    if non_bl.empty:
        return pd.DataFrame()

    svc_stats = (
        non_bl.groupby("service")[["mean_rt", "max_rt"]].agg(["mean", "std"]).fillna(0)
    )

    anomalies = []
    cfg = get_anomaly_config().get("service_response_time", {})
    for _, row in non_bl.iterrows():
        svc = row["service"]
        mean_v = row["mean_rt"]

        bl_row = baseline_agg.loc[svc] if svc in baseline_agg.index else None

        try:
            svc_mean_mean = svc_stats.loc[svc, ("mean_rt", "mean")]
            svc_mean_std = svc_stats.loc[svc, ("mean_rt", "std")]
        except KeyError:
            svc_mean_mean = svc_mean_std = 0.0

        z = _zscore(mean_v, svc_mean_mean, svc_mean_std)
        reasons = []

        if mode == MODE_ZSCORE:
            if abs(z) >= cfg.get("z_threshold", 1.5):
                reasons.append(
                    f"Avg RT {mean_v * 1000:.1f}ms — z={z:+.2f} vs service distribution"
                )
        else:  # MODE_PCT
            if bl_row is not None:
                bl_mean = float(bl_row["mean_rt"])
                if bl_mean > 0:
                    pct = ((mean_v - bl_mean) / bl_mean) * 100
                    if abs(pct) >= cfg.get("baseline_pct", 30.0):
                        direction = "above" if pct > 0 else "below"
                        reasons.append(
                            f"Avg RT {mean_v * 1000:.1f}ms is {pct:+.0f}% {direction} baseline {bl_mean * 1000:.1f}ms"
                        )

        if not reasons:
            continue

        bl_mean_v = float(bl_row["mean_rt"]) if bl_row is not None else None
        pct_sev = (
            (mean_v - (bl_mean_v or svc_mean_mean))
            / max(bl_mean_v or svc_mean_mean, 1e-6)
        ) * 100
        severity = _severity_pct(pct_sev) if mode == MODE_PCT else _severity(z)
        anomalies.append(
            {
                "scenario_id": row["scenario_id"],
                "scenario": svc,
                "generation": None,
                "anomaly_type": "Service Response Time (Latency) Spike",
                "value": round(mean_v, 3),
                "threshold": bl_mean_v if bl_mean_v is not None else float("nan"),
                "baseline_ref": bl_mean_v,
                "z_score": round(z, 3),
                "severity": severity,
                "detail": " | ".join(reasons),
            }
        )
    return pd.DataFrame(anomalies)


# Baseline extraction
def _extract_baseline(df_results: pd.DataFrame) -> dict:
    defaults = {
        "fitness_score": None,
        "duration_seconds": None,
        "health_check_failure_score": None,
        "health_check_response_time_score": None,
    }
    if df_results is None or df_results.empty:
        return defaults
    bl = df_results[df_results["scenario_id"].astype(str) == "baseline"]
    if bl.empty:
        return defaults
    row = bl.iloc[0]
    return {k: _safe_float(row, k) for k in defaults}


# Visualisation helpers
def _summary_metrics(all_anomalies: pd.DataFrame):
    total = len(all_anomalies)
    high = (
        int((all_anomalies["severity"] == "High").sum())
        if not all_anomalies.empty
        else 0
    )
    medium = (
        int((all_anomalies["severity"] == "Medium").sum())
        if not all_anomalies.empty
        else 0
    )
    low = (
        int((all_anomalies["severity"] == "Low").sum())
        if not all_anomalies.empty
        else 0
    )
    types = (
        int(all_anomalies["anomaly_type"].nunique()) if not all_anomalies.empty else 0
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Anomalies", total)
    c2.metric("High Severity", high)
    c3.metric("Medium Severity", medium)
    c4.metric("Low Severity", low)
    c5.metric("Anomaly Types", types)


def _make_scenario_label(scenario_id: str, scenario_name: str) -> str:
    """Return a human-readable label like '1 (pod-disruption)' for a scenario."""
    sid = str(scenario_id)
    sname = str(scenario_name) if scenario_name and not pd.isna(scenario_name) else ""
    if sname and sname not in ("?", sid, "nan"):
        return f"{sid} ({sname})"
    return sid


def create_anomaly_overview_plot(all_anomalies: pd.DataFrame, mode: str = MODE_ZSCORE):
    if all_anomalies.empty:
        return None
    df = all_anomalies.copy()

    # Build scenario label: "1 (pod-disruption)"
    if "scenario" in df.columns:
        df["scenario_label"] = df.apply(
            lambda r: _make_scenario_label(r["scenario_id"], r.get("scenario", "")),
            axis=1,
        )
    else:
        df["scenario_label"] = df["scenario_id"].astype(str)

    if mode == MODE_PCT and "baseline_ref" in df.columns and "value" in df.columns:
        # Use |% deviation from baseline| as bubble size
        def _abs_pct(row):
            ref = row.get("baseline_ref")
            val = row.get("value")
            if ref is not None and ref != 0 and not pd.isna(ref) and val is not None:
                return abs((val - ref) / ref * 100)
            # fall back to |z|
            return abs(row.get("z_score", 0) or 0) * 10

        df["bubble_size"] = df.apply(_abs_pct, axis=1).clip(lower=0.5)
        size_col = "bubble_size"
        size_label = "|% Deviation from Baseline|"
        title = "Anomaly Map — Anomaly Type × Scenario (bubble size = |% deviation from baseline|)"
        hover_extra = [
            "detail",
            "z_score",
            "value",
            "threshold",
            "baseline_ref",
            "scenario_id",
        ]
    else:
        df["bubble_size"] = df["z_score"].abs().clip(lower=0.1)
        size_col = "bubble_size"
        size_label = "|Z-Score|"
        title = "Anomaly Map — Anomaly Type × Scenario (bubble size = |z-score|)"
        hover_extra = ["detail", "z_score", "value", "threshold", "scenario_id"]

    # Scenarios on Y-axis, anomaly types on X-axis
    fig = px.scatter(
        df,
        x="anomaly_type",
        y="scenario_label",
        size=size_col,
        color="severity",
        color_discrete_map=SEVERITY_COLORS,
        hover_data=hover_extra,
        title=title,
        labels={
            "anomaly_type": "Anomaly Type",
            "scenario_label": "Scenario",
            size_col: size_label,
        },
        size_max=40,
        category_orders={"severity": SEVERITY_ORDER},
    )
    fig.update_layout(
        height=max(500, 60 * df["scenario_label"].nunique() + 150),
        margin=dict(l=160, r=20, t=60, b=80),
        xaxis_tickangle=-30,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        legend_title_text="Severity",
        yaxis=dict(autorange="reversed"),
    )
    return fig


def create_anomaly_type_distribution_plot(all_anomalies: pd.DataFrame):
    if all_anomalies.empty:
        return None
    counts = all_anomalies["anomaly_type"].value_counts().reset_index()
    counts.columns = ["Anomaly Type", "Count"]
    colors = [ANOMALY_COLORS.get(t, "#94a3b8") for t in counts["Anomaly Type"]]
    fig = go.Figure(
        go.Pie(
            labels=counts["Anomaly Type"],
            values=counts["Count"],
            hole=0.5,
            marker_colors=colors,
            textinfo="label+percent",
            hovertemplate="%{label}: %{value} anomalies<extra></extra>",
        )
    )
    fig.update_layout(
        title="Anomaly Distribution by Type",
        height=360,
        showlegend=False,
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def create_fitness_with_anomalies_plot(
    df_results: pd.DataFrame,
    fitness_anomalies: pd.DataFrame,
    baseline: dict,
):
    if df_results is None or df_results.empty:
        return None
    working = df_results[df_results["scenario_id"].astype(str) != "baseline"].copy()
    if working.empty:
        return None

    # Build scenario labels: "1 (pod-disruption)"
    scen_col = "scenario" if "scenario" in working.columns else None
    if scen_col:
        working["_label"] = working.apply(
            lambda r: _make_scenario_label(r["scenario_id"], r.get("scenario", "")),
            axis=1,
        )
    else:
        working["_label"] = working["scenario_id"].astype(str)

    fig = go.Figure()
    anomaly_ids = set()
    if not fitness_anomalies.empty:
        anomaly_ids.update(fitness_anomalies["scenario_id"].astype(str).tolist())
    normal = working[~working["scenario_id"].astype(str).isin(anomaly_ids)]
    anom = working[working["scenario_id"].astype(str).isin(anomaly_ids)]
    fig.add_trace(
        go.Scatter(
            x=normal["_label"],
            y=normal["fitness_score"],
            mode="markers",
            marker=dict(size=10, color="#64748b", symbol="circle"),
            name="Normal",
            hovertemplate="%{x}<br>Fitness: %{y:.3f}<extra></extra>",
        )
    )
    if not anom.empty:
        fig.add_trace(
            go.Scatter(
                x=anom["_label"],
                y=anom["fitness_score"],
                mode="markers",
                marker=dict(
                    size=16,
                    color="#ef4444",
                    symbol="x",
                    line=dict(width=2, color="#fff"),
                ),
                name="Fitness Anomaly",
                hovertemplate="%{x}<br>Fitness: %{y:.3f}<extra></extra>",
            )
        )
    if len(working) >= 2:
        lower, upper = _iqr_bounds(working["fitness_score"])
        fig.add_hline(
            y=lower,
            line_dash="dot",
            line_color="#ef4444",
            annotation_text=f"IQR Lower ({lower:.2f})",
        )
        fig.add_hline(
            y=upper,
            line_dash="dot",
            line_color="#22c55e",
            annotation_text=f"IQR Upper ({upper:.2f})",
        )
    if baseline.get("fitness_score") is not None:
        fig.add_hline(
            y=baseline["fitness_score"],
            line_dash="dash",
            line_color="#06b6d4",
            annotation_text=f"Baseline ({baseline['fitness_score']:.2f})",
        )
    fig.update_layout(
        title="Fitness Score per Scenario with Anomaly Markers",
        xaxis_title="Scenario",
        yaxis_title="Fitness Score",
        height=380,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def create_duration_z_scores_plot(df_results: pd.DataFrame, baseline: dict):
    if (
        df_results is None
        or df_results.empty
        or "duration_seconds" not in df_results.columns
    ):
        return None
    working = df_results[df_results["scenario_id"].astype(str) != "baseline"].copy()
    if working.empty:
        return None

    baseline_d = baseline.get("duration_seconds") if baseline else None

    if baseline_d is not None and baseline_d > 0:
        # RMS deviation anchored to baseline (not sample mean):
        # std_wrt_baseline = sqrt( Σ(xi − baseline)² / N )
        # z = (xi − baseline) / std_wrt_baseline
        diffs = working["duration_seconds"] - baseline_d
        std_wrt_baseline = float(np.sqrt((diffs**2).mean()))
        if std_wrt_baseline == 0:
            return None
        working["z_duration"] = diffs / std_wrt_baseline
        ref_label = f"Baseline ({baseline_d:.1f}s)"
        y_label = "Z-Score (Duration, deviation from baseline)"
        title_suffix = "vs baseline (RMS deviation)"
        thresholds = [
            (1.5, "dot", "#f97316", "+1.5σ"),
            (-1.5, "dot", "#f97316", "-1.5σ"),
            (2.5, "dash", "#ef4444", "+2.5σ"),
            (-2.5, "dash", "#ef4444", "-2.5σ"),
        ]

        def anomaly_color(z):
            return (
                "#ef4444"
                if abs(z) >= 2.5
                else "#f97316"
                if abs(z) >= 1.5
                else "#64748b"
            )
    else:
        # No baseline: fall back to std-based z-score vs run mean
        mean_d = working["duration_seconds"].mean()
        std_d = working["duration_seconds"].std(ddof=0)
        if std_d == 0:
            return None
        working["z_duration"] = (working["duration_seconds"] - mean_d) / std_d
        ref_label = None
        y_label = "Z-Score (Duration vs Run Mean)"
        title_suffix = "vs run mean"
        thresholds = [
            (1.5, "dot", "#f97316", "+1.5σ"),
            (-1.5, "dot", "#f97316", "-1.5σ"),
            (2.5, "dash", "#ef4444", "+2.5σ"),
            (-2.5, "dash", "#ef4444", "-2.5σ"),
        ]

        def anomaly_color(z):
            return (
                "#ef4444"
                if abs(z) >= 2.5
                else "#f97316"
                if abs(z) >= 1.5
                else "#64748b"
            )

    # Build scenario labels
    if "scenario" in working.columns:
        working["_label"] = working.apply(
            lambda r: _make_scenario_label(r["scenario_id"], r.get("scenario", "")),
            axis=1,
        )
    else:
        working["_label"] = working["scenario_id"].astype(str)

    working["color"] = working["z_duration"].apply(anomaly_color)
    fig = go.Figure(
        go.Bar(
            x=working["_label"],
            y=working["z_duration"],
            marker_color=working["color"],
            text=working["z_duration"].round(2),
            textposition="outside",
            customdata=working[["duration_seconds"]],
            hovertemplate=(
                "%{x}<br>Deviation from baseline: %{y:.3f}<br>Duration: %{customdata[0]:.1f}s<extra></extra>"
            ),
        )
    )
    # Threshold lines
    for yv, dash, color, label in thresholds:
        fig.add_hline(y=yv, line_dash=dash, line_color=color, annotation_text=label)
    # Zero line = baseline
    fig.add_hline(
        y=0,
        line_dash="solid",
        line_color="#06b6d4",
        annotation_text=ref_label or "Run Mean",
    )
    fig.update_layout(
        title=f"Execution Time (Duration) Deviation per Scenario — {title_suffix}",
        xaxis_title="Scenario",
        yaxis_title=y_label,
        height=350,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def create_duration_pct_baseline_plot(df_results: pd.DataFrame, baseline: dict):
    """Bar chart of % duration deviation from baseline per scenario (PCT mode)."""
    if (
        df_results is None
        or df_results.empty
        or "duration_seconds" not in df_results.columns
    ):
        return None
    working = df_results[df_results["scenario_id"].astype(str) != "baseline"].copy()
    if working.empty:
        return None

    baseline_d = baseline.get("duration_seconds") if baseline else None
    if baseline_d is None or baseline_d <= 0:
        # No baseline — nothing meaningful to show in pct mode
        return None

    working["pct_deviation"] = (
        (working["duration_seconds"] - baseline_d) / baseline_d
    ) * 100

    cfg = get_anomaly_config().get("duration", {})
    med_thresh = cfg.get("baseline_pct", 30.0)
    high_thresh = get_anomaly_config().get("severity", {}).get("high_pct", 60.0)

    def _color(pct):
        ap = abs(pct)
        if ap >= high_thresh:
            return "#ef4444"
        if ap >= med_thresh:
            return "#f97316"
        return "#64748b"

    # Build scenario labels
    if "scenario" in working.columns:
        working["_label"] = working.apply(
            lambda r: _make_scenario_label(r["scenario_id"], r.get("scenario", "")),
            axis=1,
        )
    else:
        working["_label"] = working["scenario_id"].astype(str)

    working["color"] = working["pct_deviation"].apply(_color)

    fig = go.Figure(
        go.Bar(
            x=working["_label"],
            y=working["pct_deviation"],
            marker_color=working["color"],
            text=working["pct_deviation"].round(1).astype(str) + "%",
            textposition="outside",
            customdata=working[["duration_seconds"]],
            hovertemplate=(
                f"%{{x}}<br>% Change from Baseline: %{{y:.1f}}%<br>Duration: %{{customdata[0]:.1f}}s"
                f"<br>Baseline: {baseline_d:.1f}s<extra></extra>"
            ),
        )
    )
    fig.add_hline(
        y=0,
        line_dash="solid",
        line_color="#06b6d4",
        annotation_text=f"Baseline ({baseline_d:.1f}s)",
    )
    fig.add_hline(
        y=med_thresh,
        line_dash="dot",
        line_color="#f97316",
        annotation_text=f"+{med_thresh:.0f}% (Medium)",
    )
    fig.add_hline(
        y=-med_thresh,
        line_dash="dot",
        line_color="#f97316",
        annotation_text=f"-{med_thresh:.0f}%",
    )
    fig.add_hline(
        y=high_thresh,
        line_dash="dash",
        line_color="#ef4444",
        annotation_text=f"+{high_thresh:.0f}% (High)",
    )
    fig.add_hline(
        y=-high_thresh,
        line_dash="dash",
        line_color="#ef4444",
        annotation_text=f"-{high_thresh:.0f}%",
    )
    fig.update_layout(
        title="Execution Time — % Deviation from Baseline per Scenario",
        xaxis_title="Scenario",
        yaxis_title="% Change from Baseline",
        height=350,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def create_service_response_time_zscore_heatmap_plot(df_details: pd.DataFrame):
    """Heatmap: service × scenario, colour = z-score of avg response time vs service distribution."""
    if df_details is None or df_details.empty:
        return None
    if not {"scenario_id", "service", "response_time"}.issubset(df_details.columns):
        return None

    df = df_details.copy()
    df["scenario_id"] = df["scenario_id"].astype(str)

    agg = df.groupby(["scenario_id", "service"])["response_time"].mean().reset_index()
    agg["response_time_ms"] = agg["response_time"] * 1000

    non_bl = agg[agg["scenario_id"] != "baseline"].copy()
    if non_bl.empty:
        return None

    # Compute per-service mean and std across all non-baseline scenarios
    svc_stats = (
        non_bl.groupby("service")["response_time_ms"]
        .agg(mean="mean", std="std")
        .fillna(0)
    )

    def _z(row):
        svc = row["service"]
        if svc not in svc_stats.index:
            return 0.0
        s = svc_stats.loc[svc]
        return _zscore(row["response_time_ms"], s["mean"], s["std"])

    non_bl["z_score"] = non_bl.apply(_z, axis=1)

    pivot = non_bl.pivot_table(
        index="service", columns="scenario_id", values="z_score", aggfunc="mean"
    )

    def _sort_key(s):
        try:
            return (0, int(s))
        except ValueError:
            return (-1, 0)

    sorted_cols = sorted(pivot.columns, key=_sort_key)
    pivot = pivot[sorted_cols]

    # Diverging colour scale centred at 0
    color_scale = [[0.0, "#22c55e"], [0.5, "#f8fafc"], [1.0, "#ef4444"]]

    fig = px.imshow(
        pivot,
        color_continuous_scale=color_scale,
        color_continuous_midpoint=0,
        labels=dict(x="Scenario ID", y="Service", color="Z-Score"),
        title="Service Response Time — Z-Score vs Service Distribution (Scenario × Service)",
        aspect="auto",
    )
    fig.update_traces(xgap=1, ygap=1)
    fig.update_layout(
        height=max(300, 60 * len(pivot) + 100),
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=50, b=40),
        xaxis=dict(type="category"),
    )
    return fig


def create_service_response_time_heatmap_plot(df_details: pd.DataFrame):
    """Heatmap: service × scenario, colour = % change in avg response time vs baseline."""
    if df_details is None or df_details.empty:
        return None
    if not {"scenario_id", "service", "response_time"}.issubset(df_details.columns):
        return None

    df = df_details.copy()
    df["scenario_id"] = df["scenario_id"].astype(str)

    # Per (scenario, service) mean response time in ms
    agg = df.groupby(["scenario_id", "service"])["response_time"].mean().reset_index()
    agg["response_time_ms"] = agg["response_time"] * 1000

    # Extract baseline avg per service
    baseline_rt = agg[agg["scenario_id"] == "baseline"].set_index("service")[
        "response_time_ms"
    ]

    if baseline_rt.empty:
        # No baseline: fall back to raw ms heatmap
        pivot = agg.pivot_table(
            index="service",
            columns="scenario_id",
            values="response_time_ms",
            aggfunc="mean",
        )
        color_label = "Avg RT (ms)"
        title = "Service Avg Response Time — ms (no baseline found)"
        color_scale = [
            [0, "#0f172a"],
            [0.4, "#1d4ed8"],
            [0.7, "#f97316"],
            [1, "#ef4444"],
        ]
        zmid = None
    else:
        # % change = (scenario_rt - baseline_rt) / baseline_rt * 100
        non_bl = agg[agg["scenario_id"] != "baseline"].copy()
        non_bl["pct_change"] = non_bl.apply(
            lambda r: (
                (
                    (r["response_time_ms"] - baseline_rt[r["service"]])
                    / baseline_rt[r["service"]]
                    * 100
                )
                if r["service"] in baseline_rt.index
                else float("nan")
            ),
            axis=1,
        )
        pivot = non_bl.pivot_table(
            index="service", columns="scenario_id", values="pct_change", aggfunc="mean"
        )
        color_label = "% Change from Baseline"
        title = "Service Response Time — % Change from Baseline (Scenario × Service)"
        color_scale = [[0.0, "#22c55e"], [0.5, "#f8fafc"], [1.0, "#ef4444"]]
        zmid = 0

    # Sort columns: numeric IDs ascending
    def _sort_key(s):
        try:
            return (0, int(s))
        except ValueError:
            return (-1, 0)  # baseline first (only in fallback)

    sorted_cols = sorted(pivot.columns, key=_sort_key)
    pivot = pivot[sorted_cols]

    fig = px.imshow(
        pivot,
        color_continuous_scale=color_scale,
        color_continuous_midpoint=zmid,
        labels=dict(x="Scenario ID", y="Service", color=color_label),
        title=title,
        aspect="auto",
    )
    fig.update_traces(xgap=1, ygap=1)
    fig.update_layout(
        height=max(300, 60 * len(pivot) + 100),
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=50, b=40),
        xaxis=dict(type="category"),
    )
    return fig


def _anomaly_detail_table(all_anomalies: pd.DataFrame):
    if all_anomalies.empty:
        st.info("No anomalies detected.")
        return
    df = all_anomalies.copy()
    df["severity_display"] = df["severity"]
    display_cols = [
        "severity_display",
        "anomaly_type",
        "scenario_id",
        "scenario",
        "generation",
        "value",
        "threshold",
        "baseline_ref",
        "z_score",
        "detail",
    ]
    avail = [c for c in display_cols if c in df.columns]
    view = df[avail].rename(
        columns={
            "severity_display": "Severity",
            "anomaly_type": "Type",
            "scenario_id": "Scenario ID",
            "scenario": "Scenario Name",
            "generation": "Gen",
            "value": "Observed",
            "threshold": "Threshold",
            "baseline_ref": "Baseline Ref",
            "z_score": "Z-Score",
            "detail": "Details",
        }
    )
    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        column_config={
            "Severity": st.column_config.TextColumn("Severity", width="small"),
            "Type": st.column_config.TextColumn("Anomaly Type", width="medium"),
            "Scenario ID": st.column_config.TextColumn("ID", width="small"),
            "Scenario Name": st.column_config.TextColumn("Scenario", width="medium"),
            "Gen": st.column_config.NumberColumn("Gen", format="%d", width="small"),
            "Observed": st.column_config.NumberColumn("Observed", format="%.3f"),
            "Threshold": st.column_config.NumberColumn("Threshold", format="%.3f"),
            "Baseline Ref": st.column_config.NumberColumn("Baseline", format="%.3f"),
            "Z-Score": st.column_config.NumberColumn("Z-Score", format="%.3f"),
            "Details": st.column_config.TextColumn("Details", width="large"),
        },
    )


# Main entry point
def render_anomalies(
    df_results: pd.DataFrame,
    df_health: Optional[pd.DataFrame] = None,
    df_results_all: Optional[pd.DataFrame] = None,
    df_details: Optional[pd.DataFrame] = None,
    global_services: Optional[List[str]] = None,
    filtered_scenario_ids: Optional[List] = None,
):
    """
    Render the full Anomaly Detection tab.

    Parameters
    ----------
    df_results        : Filtered results from all.csv.
    df_health         : health_check_report.csv data (already filtered).
    df_results_all    : Unfiltered all.csv data (includes baseline row).
    df_details        : Per-request YAML telemetry from load_detailed_scenarios_data.
    global_services   : Service filter from sidebar.
    filtered_scenario_ids : Scenario IDs currently active (for df_details filter).
    """
    st.header("Anomaly Detection")
    st.caption(
        "Anomalies are detected using **IQR fences**, **Z-scores**, and "
        "**rule-based baseline comparison**"
    )

    # Detection Mode toggle
    mode_label = st.radio(
        "**Detection Mode**",
        ["% Deviation from Baseline", "Z-Score (statistical)"],
        horizontal=True,
        key="anom_mode",
        help=(
            "**Z-Score:** flags scenarios that are statistically unusual within the run "
            "(|z| ≥ 1.5 = medium, |z| ≥ 2.5 = high).\n\n"
            "**% Deviation:** flags scenarios relative to the baseline scenario "
            "(|Δ| ≥ 30% = medium, |Δ| ≥ 60% = high)."
        ),
    )
    mode = MODE_ZSCORE if "Z-Score" in mode_label else MODE_PCT

    # Legend & Detection Methods
    if mode == MODE_ZSCORE:
        legend_md = """
### Z-Score Detection — How It Works

For each metric **x** across *N* non-baseline runs:

| Symbol | Formula |
|:---|:---|
| Population mean | `μ  = (x₁ + x₂ + … + xₙ) / N` |
| Population std dev | `σ  = √[ Σ(xᵢ − μ)² / N ]` |
| Z-score | `z  = (x − μ) / σ` |

> **Severity bands:** `|z| ≥ 2.5` →  High &nbsp;|&nbsp; `|z| ≥ 1.5` → Medium &nbsp;|&nbsp; else → Low

#### IQR Fences (used for Fitness & HC Failure Surge)

```
Q1, Q3 = 25th / 75th percentile of the metric across runs
IQR    = Q3 − Q1
Lower fence = Q1 − 1.5 × IQR
Upper fence = Q3 + 1.5 × IQR
→ Flagged when x < Lower fence  OR  x > Upper fence
```

#### Per-Detector Formulas

| Detector | Metric | Method | Trigger |
|---|---|---|---|
| **Low / High Fitness** | `fitness_score` | IQR fence | x < Q1−1.5·IQR or x > Q3+1.5·IQR |
| **Duration Anomaly** | `duration_seconds` | Z-score (RMS σ vs baseline if available) | `\|z\| ≥ 1.5` |
| **HC Failure Surge** | `health_check_failure_score` | IQR fence | x > Q3+1.5·IQR |
| **Fitness Regression** | Best fitness per generation | Gen-over-gen delta | `drop% = (prev−cur)/prev×100`; High if drop > 20% |
| **Service Failure Rate** | Per-service failure_rate | Z-score vs service distribution | `\|z\| ≥ 1.5` |
| **Krkn Failure Score** | `krkn_failure_score` | Non-zero sentinel + IQR | Non-zero → Medium; above IQR upper fence → High |
| **HC Response Time** | `health_check_response_time_score` | IQR + Z-score | IQR breach OR `\|z\| ≥ 1.5` |
| **Service RT Spike** | Avg `response_time` per service | Z-score vs per-service distribution | `\|z\| ≥ 1.5` |

*Duration uses RMS deviation: `σ_rms = √[ Σ(dᵢ − baseline)² / N ]` when a baseline is available; falls back to population σ otherwise.*
"""
    else:
        legend_md = """
### % Deviation from Baseline — How It Works

For each value **x** and its baseline reference **b**:

| Symbol | Formula |
|:---|:---|
| Percent deviation | `Δ% = (x − b) / \|b\| × 100` |

> **Severity bands:** `\|Δ%\| ≥ 60` → High &nbsp;|&nbsp; `\|Δ%\| ≥ 30` → Medium &nbsp;|&nbsp; else → Low

> **Note:** IQR fences (Q1−1.5·IQR / Q3+1.5·IQR) are still applied for Fitness as an additional gate.

#### Per-Detector Formulas

| Detector | Baseline reference *b* | Trigger condition |
|---|---|---|
| **Low / High Fitness** | Baseline scenario `fitness_score` | IQR fence breach **and/or** `Δ% < 0` below baseline |
| **Duration Anomaly** | Baseline scenario `duration_seconds` | `\|Δ%\| ≥ 30` |
| **HC Failure Surge** | Baseline `health_check_failure_score` | `\|Δ%\| ≥ 30` |
| **Fitness Regression** | Previous generation best fitness | `drop% = (prev−cur)/prev×100`; High if drop > 20%, Medium if drop > 10% |
| **Service Failure Rate** | Baseline per-service failure rate | `\|Δ%\| ≥ 30` |
| **Krkn Failure Score** | — (non-zero sentinel) | Non-zero → Medium; above IQR upper fence → High |
| **HC Response Time** | Baseline `health_check_response_time_score` | `\|Δ%\| ≥ 30` |
| **Service RT Spike** | Baseline per-service avg `response_time` | `\|Δ%\| ≥ 30` |

*Fitness Regression and Krkn Failure Score do not use % deviation — they use fixed rule-based logic regardless of mode.*
"""

    with st.expander("Anomaly Type Legend & Detection Methods", expanded=False):
        st.markdown(legend_md)

    # Prefer unfiltered dataset so baseline row is always present
    src: pd.DataFrame = pd.DataFrame(
        df_results_all if df_results_all is not None else df_results
    )

    if src is None or src.empty:
        st.warning("No scenario results available for anomaly analysis.")
        return

    # Apply service + scenario filter to df_details for service-level detectors
    df_det = None
    if df_details is not None and not df_details.empty:
        df_det = df_details.copy()
        df_det["scenario_id"] = df_det["scenario_id"].astype(str)
        if filtered_scenario_ids:
            str_ids = [str(x) for x in filtered_scenario_ids] + ["baseline"]
            df_det = df_det[df_det["scenario_id"].isin(str_ids)]
        if global_services:
            df_det = df_det[df_det["service"].isin(global_services)]

    # Baseline extraction
    baseline = _extract_baseline(src)

    # Run all detectors with chosen mode
    fitness_anom = detect_fitness_iqr_anomalies(
        src, baseline.get("fitness_score"), mode=mode
    )
    duration_anom = detect_duration_anomalies(
        src, baseline.get("duration_seconds"), mode=mode
    )
    hc_anom = detect_hc_failure_surge(
        src, baseline.get("health_check_failure_score"), mode=mode
    )
    regression_anom = detect_fitness_regression(src)
    service_anom = detect_service_failure_spikes(df_health, mode=mode)
    krkn_anom = detect_krkn_failure_score_anomalies(src)
    hc_rt_anom = detect_hc_response_time_anomalies(
        src, baseline.get("health_check_response_time_score"), mode=mode
    )
    svc_rt_anom = detect_service_response_time_spikes(
        df_det, global_services, mode=mode
    )

    all_parts = [
        fitness_anom,
        duration_anom,
        hc_anom,
        regression_anom,
        service_anom,
        krkn_anom,
        hc_rt_anom,
        svc_rt_anom,
    ]
    non_empty = [p.dropna(axis=1, how="all") for p in all_parts if not p.empty]
    all_anomalies = (
        pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()
    )

    # Normalise column types for Arrow/Streamlit serialisation
    if not all_anomalies.empty:
        if "scenario_id" in all_anomalies.columns:
            all_anomalies["scenario_id"] = all_anomalies["scenario_id"].astype(str)
        if "generation" in all_anomalies.columns:
            all_anomalies["generation"] = pd.to_numeric(
                all_anomalies["generation"], errors="coerce"
            ).astype("Int64")

    # Post-filter: keep only anomalies for the selected scenarios.
    # Detection ran on the FULL population (needed for valid stats), so we filter
    # the results here rather than restricting the input data.
    if not all_anomalies.empty and filtered_scenario_ids:

        def _norm(v) -> str:
            try:
                return str(int(float(v)))
            except (ValueError, TypeError):
                return str(v)

        normed_filter = set(filtered_scenario_ids)  # already normalised by app.py
        all_anomalies = all_anomalies[
            all_anomalies["scenario_id"].apply(_norm).isin(normed_filter)
        ]

    st.divider()

    # Summary metrics
    st.subheader("Anomaly Summary")
    _summary_metrics(all_anomalies)

    if all_anomalies.empty:
        st.success("No anomalies detected across all checks.")
        return

    st.divider()

    # Overview charts
    col_a, col_b = st.columns([2, 1])
    with col_a:
        fig_overview = create_anomaly_overview_plot(all_anomalies, mode=mode)
        if fig_overview:
            st.plotly_chart(fig_overview, width="stretch")
    with col_b:
        fig_dist = create_anomaly_type_distribution_plot(all_anomalies)
        if fig_dist:
            st.plotly_chart(fig_dist, width="stretch")

    st.divider()

    # Fitness & Duration deep-dives
    st.subheader("Fitness Score Anomalies")
    fig_fitness = create_fitness_with_anomalies_plot(src, fitness_anom, baseline)
    if fig_fitness:
        st.plotly_chart(fig_fitness, width="stretch")
    else:
        st.info("Not enough data to plot fitness anomalies.")

    st.subheader("Execution Time Anomalies")
    if mode == MODE_ZSCORE:
        fig_duration = create_duration_z_scores_plot(src, baseline)
        caption_duration = "Z-Score deviation from baseline (or run mean when no baseline). |z|≥1.5 = Medium, |z|≥2.5 = High."
    else:
        fig_duration = create_duration_pct_baseline_plot(src, baseline)
        caption_duration = (
            "% deviation from baseline duration. |Δ|≥30% = Medium, |Δ|≥60% = High."
        )
    st.caption(caption_duration)
    if fig_duration:
        st.plotly_chart(fig_duration, width="stretch")
    else:
        st.info(
            "Not enough data to plot duration anomalies (baseline required for % Deviation mode)."
        )

    # Service response-time deep-dives from YAML telemetry
    if df_det is not None and not df_det.empty:
        st.divider()
        st.subheader("Service Response Time (Latency) Analysis")
        if mode == MODE_ZSCORE:
            st.caption(
                "Heatmap shows per-service response time z-score across scenarios "
                "(z-score computed vs the per-service distribution across all non-baseline scenarios)."
            )
            fig_rt_heatmap = create_service_response_time_zscore_heatmap_plot(df_det)
        else:
            st.caption(
                "Heatmap shows % change in mean response time compared to the baseline scenario "
                "per service. Green = faster than baseline, Red = slower."
            )
            fig_rt_heatmap = create_service_response_time_heatmap_plot(df_det)
        if fig_rt_heatmap:
            st.plotly_chart(fig_rt_heatmap, width="stretch")
        else:
            st.info("Not enough data to plot response time heatmap.")

    st.divider()

    # Detailed anomaly table
    st.subheader("All Detected Anomalies")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        sev_filter = st.multiselect(
            "Filter by Severity:",
            options=["High", "Medium", "Low"],
            default=[],
            help="Leave blank to show all severities.",
        )
    with col_f2:
        type_filter = st.multiselect(
            "Filter by Anomaly Type:",
            options=sorted(all_anomalies["anomaly_type"].unique().tolist()),
            default=[],
            help="Leave blank to show all types.",
        )
    view_df = all_anomalies.copy()
    if sev_filter:
        view_df = view_df[view_df["severity"].isin(sev_filter)]
    if type_filter:
        view_df = view_df[view_df["anomaly_type"].isin(type_filter)]
    if mode == MODE_PCT and "z_score" in view_df.columns:
        view_df = view_df.drop(columns=["z_score"])
    _anomaly_detail_table(view_df)
