import math

import pandas as pd
import streamlit as st


def _fitness_frame(items):
    frame = pd.DataFrame(
        [
            {
                "name": item["name"],
                "category": item["category"] or "—",
                "type": item["type"] or "—",
                "weight": item["weight"] if item["enabled"] else math.nan,
                "status": "in use" if item["enabled"] else "rejected",
                "reason": item["reason"] or "—",
                "query": item["query"],
            }
            for item in items
        ]
    )
    if not frame.empty:
        frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce")
    return frame


def render_fitness_section(config_data, items):
    st.subheader("Fitness Function")
    fitness_function = (config_data or {}).get("fitness_function") or {}

    flags = [
        key
        for key in (
            "include_krkn_failure",
            "include_health_check_failure",
            "include_health_check_response_time",
        )
        if fitness_function.get(key)
    ]
    st.caption(
        "Extra score components: " + (", ".join(flags) if flags else "none") + "."
    )

    if fitness_function.get("query"):
        st.write("Single-query mode:")
        st.code(fitness_function["query"], language="promql")
        st.caption(
            f"Type: {fitness_function.get('type', 'point')}. Per-query items are "
            "ignored while `query` is set."
        )

    if not items:
        st.info("No per-query fitness items in this config.")
        return

    st.dataframe(
        _fitness_frame(items),
        column_config={
            "name": st.column_config.TextColumn("Query", width="medium"),
            "category": st.column_config.TextColumn("Category"),
            "type": st.column_config.TextColumn("Type"),
            "weight": st.column_config.NumberColumn("Weight", format="%.4f"),
            "status": st.column_config.TextColumn("Status"),
            "reason": st.column_config.TextColumn("Reason", width="medium"),
            "query": st.column_config.TextColumn("PromQL", width="large"),
        },
        width="stretch",
        hide_index=True,
    )


def render_health_check_section(config_data, health_check_recos):
    st.subheader("Health Checks")
    health_checks = (config_data or {}).get("health_checks") or {}
    applications = health_checks.get("applications") or []

    if applications:
        st.dataframe(
            pd.DataFrame(applications),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info(
            "No health-check applications configured — health-check scores will "
            "stay at 0 for every scenario."
        )

    if health_check_recos:
        st.caption("Discover found these services but left them commented out:")
        st.dataframe(
            pd.DataFrame(health_check_recos),
            column_config={
                "name": st.column_config.TextColumn("Service"),
                "url": st.column_config.TextColumn("URL", width="large"),
                "reason": st.column_config.TextColumn("Reason"),
            },
            width="stretch",
            hide_index=True,
        )


def render_scenario_section(config_data):
    st.subheader("Scenarios")
    scenarios = (config_data or {}).get("scenario") or {}
    if not scenarios:
        st.info("No scenario section in this config.")
        return

    frame = pd.DataFrame(
        [
            {"scenario": name, "enabled": bool((value or {}).get("enable"))}
            for name, value in scenarios.items()
        ]
    )
    enabled_count = int(frame["enabled"].sum())
    st.caption(f"{enabled_count} of {len(frame)} scenario types enabled.")
    st.dataframe(
        frame,
        column_config={
            "scenario": st.column_config.TextColumn("Scenario"),
            "enabled": st.column_config.CheckboxColumn("Enabled"),
        },
        width="stretch",
        hide_index=True,
    )


def render_cluster_section(config_data):
    st.subheader("Cluster Components")
    components = (config_data or {}).get("cluster_components") or {}
    namespaces = components.get("namespaces") or []
    nodes = components.get("nodes") or []

    cols = st.columns(2)
    cols[0].metric("Namespaces", len(namespaces))
    cols[1].metric("Nodes", len(nodes))

    if namespaces:
        st.dataframe(
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
            ),
            width="stretch",
            hide_index=True,
        )


def render_config(config_data, items=None, health_check_recos=None):
    st.header("Krkn-AI Configuration")
    if not config_data:
        st.write("Configuration file not found.")
        return

    render_fitness_section(config_data, items or [])
    st.divider()
    render_health_check_section(config_data, health_check_recos or [])
    st.divider()
    render_scenario_section(config_data)
    st.divider()
    render_cluster_section(config_data)
    st.divider()
    with st.expander("Raw configuration", expanded=False):
        st.json(config_data)
