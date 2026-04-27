import streamlit as st
import plotly.express as px
import plotly.graph_objects as go


def render_health_checks(df, global_services=None):
    st.header("Service Health Checks")
    if df is None or df.empty:
        st.warning("Health check data not yet available.")
        return

    if "failure_rate" not in df.columns:
        df["failure_rate"] = df["failure_count"] / (
            df["success_count"] + df["failure_count"]
        ).clip(lower=1)
    if "variance" not in df.columns:
        df["variance"] = (df["max_response_time"] - df["min_response_time"]) / df[
            "average_response_time"
        ].clip(lower=0.0001)

    # Apply global service filter
    if global_services:
        df = df[df["component_name"].isin(global_services)]

    st.subheader("Interactive Heatmap")
    metric_col = st.selectbox(
        "Select Metric:",
        ["average_response_time", "max_response_time", "min_response_time"],
    )

    heat_df = (
        df.groupby(["component_name", "scenario_id"])[metric_col].mean().reset_index()
    )
    heat_df["scenario_id"] = heat_df["scenario_id"].astype(str)

    # Pivot into a matrix: rows = scenario_id, cols = component_name
    pivot_df = heat_df.pivot_table(
        index="scenario_id", columns="component_name", values=metric_col
    )

    fig = px.imshow(
        pivot_df,
        color_continuous_scale="RdYlGn_r",
        zmin=0,  # Color Scale Mapping
        title=f"{metric_col} Heatmap",
        labels={"x": "Component", "y": "Scenario ID", "color": metric_col},
        aspect="auto",
    )
    fig.update_layout(xaxis_title="Component", yaxis_title="Scenario ID")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Scenario trends line chart
    st.subheader("Scenario Trends")
    line_metric = st.selectbox(
        "Trend Metric:",
        ["average_response_time", "max_response_time", "min_response_time"],
        key="line_metric",
    )

    line_df = df.sort_values("scenario_id")
    line_df["scenario_id"] = line_df["scenario_id"].astype(str)
    fig2 = px.line(
        line_df,
        x="scenario_id",
        y=line_metric,
        color="component_name",
        markers=True,
        title=f"{line_metric} Trends",
    )
    fig2.update_layout(xaxis={"type": "category"})
    st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # stacked bar plot
    st.subheader("Success vs Failure")
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
    fig3 = px.bar(
        melt_bar,
        x="component_name",
        y="Count",
        color="Status",
        title="Success vs Failure Counts",
        barmode="stack",
        color_discrete_map={"success_count": "#28a745", "failure_count": "#dc3545"},
    )
    st.plotly_chart(fig3, use_container_width=True)

    st.divider()

    # Radar chart
    st.subheader("Resilience Radar Chart")
    radar_df = df.copy()
    radar_df["scenario_id"] = radar_df["scenario_id"].astype(str)
    if not radar_df.empty:
        radar_df["score"] = 1 / radar_df["average_response_time"].clip(lower=0.0001)
        fig4 = px.line_polar(
            radar_df,
            r="score",
            theta="component_name",
            line_close=True,
            color="scenario_id",
            title="Resilience Profile",
        )
        fig4.update_traces(fill="toself", opacity=0.5)
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.info("No data for radar chart.")

    st.divider()

    # min-max range plot
    st.subheader("Response Range Plot (Min-Max)")
    range_df = (
        df.groupby("component_name")
        .agg({"min_response_time": "min", "max_response_time": "max"})
        .reset_index()
    )
    fig5 = go.Figure()
    for _, row in range_df.iterrows():
        fig5.add_trace(
            go.Scatter(
                x=[row["component_name"], row["component_name"]],
                y=[row["min_response_time"], row["max_response_time"]],
                mode="lines+markers",
                name=row["component_name"],
                showlegend=False,
                marker={"symbol": "line-ew", "size": 15},
            )
        )
    fig5.update_layout(
        title="Min/Max Range per Component",
        xaxis_title="Component",
        yaxis_title="Response Time Range",
    )
    st.plotly_chart(fig5, use_container_width=True)

    st.divider()

    # table
    st.subheader("Top-K Worst Components Table")
    sort_by = st.selectbox(
        "Sort Table By (Descending):",
        ["average_response_time", "failure_count", "failure_rate", "variance"],
    )
    worst_k = st.number_input(
        "Top K Slowest Components:", min_value=1, value=10, max_value=50, key="worst_k"
    )
    worst_table = df.sort_values(by=sort_by, ascending=False).head(worst_k)
    st.dataframe(worst_table)
