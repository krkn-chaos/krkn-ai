import streamlit as st
import plotly.express as px
import plotly.graph_objects as go


def _get_scenario_label(scen_id, scen_id_to_name):
    if scen_id_to_name:
        name = scen_id_to_name.get(str(scen_id)) or scen_id_to_name.get(
            int(scen_id) if str(scen_id).isdigit() else scen_id
        )
        if name:
            return f"{scen_id} – {name}"
    return str(scen_id)


def create_runtime_telemetry_plot(target_df, scen_id_to_name=None):
    if target_df is None or target_df.empty:
        return None

    fig = go.Figure()

    for scen in target_df["scenario_id"].unique():
        for srv in target_df[target_df["scenario_id"] == scen]["service"].unique():
            srv_df = target_df[
                (target_df["scenario_id"] == scen) & (target_df["service"] == srv)
            ]

            fig.add_trace(
                go.Scatter(
                    x=srv_df["seconds_into_scenario"],
                    y=srv_df["response_time"],
                    mode="lines+markers",
                    name=f"{srv} ({_get_scenario_label(scen, scen_id_to_name)})",
                    customdata=srv_df[["timestamp", "status_code", "error"]],
                    hovertemplate="Service: "
                    + srv
                    + "<br>Scenario: "
                    + _get_scenario_label(scen, scen_id_to_name)
                    + "<br>Time: %{customdata[0]}<br>Seconds: %{x:.2f}s<br>Response Time: %{y:.4f}s<br>Status: %{customdata[1]}<br>Error: %{customdata[2]}<extra></extra>",
                    marker=dict(size=6),
                )
            )

    fig.update_layout(
        title="Runtime Telemetry: Service Response Time (Latency) vs Scenario Execution Time (Duration)",
        xaxis_title="Seconds into Scenario Execution Time (s)",
        yaxis_title="Service Response Time / Latency (s)",
        hovermode="closest",
    )
    return fig


def create_success_timeline_plot(target_df, scen_id_to_name=None):
    if target_df is None or target_df.empty:
        return None

    succ_df = target_df.copy()
    if "success" not in succ_df.columns:
        return None

    succ_df["time_sec"] = succ_df["seconds_into_scenario"].astype(int)
    agg_df = succ_df.groupby(["service", "time_sec"])["success"].min().reset_index()
    agg_df["success_int"] = agg_df["success"].astype(int)

    pivot_df = agg_df.pivot(index="service", columns="time_sec", values="success_int")

    scen_label = ", ".join(
        _get_scenario_label(s, scen_id_to_name) for s in succ_df["scenario_id"].unique()
    )
    fig_succ = px.imshow(
        pivot_df,
        color_continuous_scale=[[0.0, "red"], [1.0, "green"]],
        zmin=0,
        zmax=1,
        labels=dict(x="Seconds into Scenario (s)", y="Application", color="Status"),
        aspect="auto",
        title=f"Success Timeline (Scenarios: {scen_label})",
    )
    fig_succ.update_layout(coloraxis_showscale=False)
    fig_succ.update_traces(
        xgap=1,
        ygap=1,
        hovertemplate="Application: %{y}<br>Seconds: %{x}s<br>Status (1=Success, 0=Fail): %{z}<extra></extra>",
    )
    return fig_succ


def render_detailed_scenarios(
    df_details, global_scenarios=None, global_services=None, scen_id_to_name=None
):
    st.header("Detailed Scenarios Runtime Tracking")
    if df_details is None or df_details.empty:
        st.warning("No detailed scenario YAML telemetry available.")
        return

    # global filters
    target_df = df_details.copy()
    if global_scenarios:
        target_df = target_df[
            target_df["scenario_id"].isin([str(s) for s in global_scenarios])
        ]
    if global_services:
        target_df = target_df[target_df["service"].isin(global_services)]

    if target_df.empty:
        st.info("No data available for the selected filters.")
        return

    fig = create_runtime_telemetry_plot(target_df, scen_id_to_name)
    if fig:
        st.plotly_chart(fig, width="stretch")

    st.divider()

    # success per service over time
    st.subheader("Success per Service Over Time")
    fig_succ = create_success_timeline_plot(target_df, scen_id_to_name)
    if fig_succ:
        st.plotly_chart(fig_succ, width="stretch")
    else:
        st.info("No data available for Success Plot.")
