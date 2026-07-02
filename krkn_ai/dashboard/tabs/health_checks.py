import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go


def create_health_checks_heatmap_plot(df, metric_col="average_response_time"):
    if df is None or df.empty:
        return None

    df = df.copy()

    def _norm_id(v):
        try:
            return str(int(float(v)))
        except (ValueError, TypeError):
            return str(v)

    df["scenario_id"] = df["scenario_id"].apply(_norm_id)

    heat_df = (
        df.groupby(["component_name", "scenario_id"])[metric_col].mean().reset_index()
    )

    # Pivot into a matrix: rows = scenario_id, cols = component_name
    pivot_df = heat_df.pivot_table(
        index="scenario_id", columns="component_name", values=metric_col
    )

    def _sort_key(s):
        try:
            return (0, int(s))
        except (ValueError, TypeError):
            return (-1, 0)

    pivot_df = pivot_df.loc[sorted(pivot_df.index, key=_sort_key)]

    # Keep raw values for tooltip
    fig = px.imshow(
        pivot_df,
        color_continuous_scale="OrRd",
        title=f"{metric_col} Heatmap",
        labels={
            "x": "Component",
            "y": "Scenario ID",
            "color": metric_col,
        },
        aspect="auto",
    )
    fig.update_traces(xgap=1, ygap=1)
    fig.update_layout(
        xaxis_title="Component",
        yaxis_title="Scenario ID",
        yaxis=dict(type="category"),
        coloraxis_colorbar_title=metric_col,
    )
    return fig


def create_health_checks_trend_plot(df, line_metric="average_response_time"):
    if df is None or df.empty:
        return None
    bar_df = df.copy()

    def _norm_id(v):
        try:
            return str(int(float(v)))
        except (ValueError, TypeError):
            return str(v)

    bar_df["scenario_id"] = bar_df["scenario_id"].apply(_norm_id)

    # Sort scenario IDs numerically where possible
    def _sort_key(s):
        try:
            return (0, int(s))
        except (ValueError, TypeError):
            return (-1, 0)

    sorted_ids = sorted(bar_df["scenario_id"].unique(), key=_sort_key)
    bar_df["scenario_id"] = pd.Categorical(
        bar_df["scenario_id"], categories=sorted_ids, ordered=True
    )
    bar_df = bar_df.sort_values("scenario_id")

    fig = px.bar(
        bar_df,
        x="scenario_id",
        y=line_metric,
        color="component_name",
        barmode="group",
        title=f"{line_metric} per Scenario",
        labels={"scenario_id": "Scenario ID", "component_name": "Component"},
    )
    fig.update_layout(xaxis={"type": "category"})
    return fig


def create_success_vs_failure_plot(df):
    if df is None or df.empty:
        return None
    bar_base_df = df.copy()
    bar_df = (
        bar_base_df.groupby("component_name")[["success_count", "failure_count"]]
        .sum()
        .reset_index()
    )
    melt_bar = bar_df.melt(
        id_vars=["component_name"],
        value_vars=["success_count", "failure_count"],
        var_name="Status",
        value_name="Count",
    )
    fig = px.bar(
        melt_bar,
        x="component_name",
        y="Count",
        color="Status",
        title="Success vs Failure Counts",
        barmode="stack",
        color_discrete_map={"success_count": "#28a745", "failure_count": "#dc3545"},
    )
    return fig


def create_resilience_radar_plot(df):
    if df is None or df.empty:
        return None
    radar_df = df.copy()
    radar_df["scenario_id"] = radar_df["scenario_id"].astype(str)
    if not radar_df.empty:
        radar_df["score"] = 1 / radar_df["average_response_time"].clip(lower=0.0001)
        fig = px.line_polar(
            radar_df,
            r="score",
            theta="component_name",
            line_close=True,
            color="scenario_id",
            title="Resilience Profile",
        )
        fig.update_traces(fill="toself", opacity=0.5)
        return fig
    return None


def create_response_range_plot(df):
    if df is None or df.empty:
        return None
    range_df = (
        df.groupby("component_name")
        .agg({"min_response_time": "min", "max_response_time": "max"})
        .reset_index()
    )
    fig = go.Figure()
    for _, row in range_df.iterrows():
        fig.add_trace(
            go.Scatter(
                x=[row["component_name"], row["component_name"]],
                y=[row["min_response_time"], row["max_response_time"]],
                mode="lines+markers",
                name=row["component_name"],
                showlegend=False,
                marker={"symbol": "line-ew", "size": 15},
            )
        )
    fig.update_layout(
        title="Min/Max Range (Latency) per Component",
        xaxis_title="Component",
        yaxis_title="Response Time (Latency) Range (s)",
    )
    return fig


def render_health_checks(df, global_services=None):
    st.header("Service Health Checks")
    if df is None or df.empty:
        st.warning("Health check data not yet available.")
        return

    df = df.copy()

    if "failure_rate" not in df.columns:
        df["failure_rate"] = df["failure_count"] / (
            df["success_count"] + df["failure_count"]
        ).clip(lower=1)
    if "variance" not in df.columns:
        df["variance"] = (df["max_response_time"] - df["min_response_time"]) / df[
            "average_response_time"
        ].clip(lower=0.0001)

    # global service filter
    if global_services:
        df = df[df["component_name"].isin(global_services)]

    st.subheader("Latency Interactive Heatmap")
    metric_col = st.selectbox(
        "Select Metric:",
        ["average_response_time", "max_response_time", "min_response_time"],
    )

    fig = create_health_checks_heatmap_plot(df, metric_col)
    st.plotly_chart(fig, width="stretch")

    st.divider()

    # Scenario trends line chart
    st.subheader("Scenario Trends")
    line_metric = st.selectbox(
        "Trend Metric:",
        ["average_response_time", "max_response_time", "min_response_time"],
        key="line_metric",
    )

    fig2 = create_health_checks_trend_plot(df, line_metric)
    st.plotly_chart(fig2, width="stretch")

    st.divider()

    # stacked bar plot
    st.subheader("Success vs Failure")
    fig3 = create_success_vs_failure_plot(df)
    st.plotly_chart(fig3, width="stretch")

    st.divider()

    # Radar chart
    st.subheader("Resilience Radar Chart")
    fig4 = create_resilience_radar_plot(df)
    if fig4:
        st.plotly_chart(fig4, width="stretch")
    else:
        st.info("No data for radar chart.")

    st.divider()

    # min-max range plot
    st.subheader("Response Range Plot (Min-Max)")
    fig5 = create_response_range_plot(df)
    st.plotly_chart(fig5, width="stretch")

    st.divider()

    # table
    st.subheader("Components Table")
    sort_by = st.selectbox(
        "Sort Table By (Descending):",
        ["average_response_time", "failure_count", "failure_rate", "variance"],
    )
    worst_k = st.number_input(
        "Top K Worst Performing Components:",
        min_value=1,
        value=10,
        max_value=50,
        key="worst_k",
    )
    worst_table = df.sort_values(by=sort_by, ascending=False).head(worst_k)
    st.dataframe(worst_table)
