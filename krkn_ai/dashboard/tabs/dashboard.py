import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go


def render_summary(df):
    st.header("Experiment Summary")
    if df is None or df.empty:
        st.warning("Results data not yet available. Waiting for Krkn-AI engine...")
        return

    # stats directly from CSV data
    generations_completed = (
        int(df["generation_id"].max() + 1) if "generation_id" in df.columns else 0
    )
    scenarios_executed = len(df)
    best_fitness = df["fitness_score"].max() if "fitness_score" in df.columns else 0.0
    avg_fitness = df["fitness_score"].mean() if "fitness_score" in df.columns else 0.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Generations Completed", generations_completed)
    col2.metric("Scenarios Executed", scenarios_executed)
    col3.metric("Best Fitness Score", f"{best_fitness:.4f}")
    col4.metric("Avg Fitness Score", f"{avg_fitness:.4f}")


def create_fitness_evolution_plot(df):
    if df is None or df.empty or "generation_id" not in df.columns:
        return None

    # Grouping CSV by generation to plot Best vs Average
    grouped = (
        df.groupby("generation_id")["fitness_score"].agg(["mean", "max"]).reset_index()
    )
    if grouped.empty:
        return None

    grouped.rename(
        columns={"mean": "Average Fitness", "max": "Best Fitness"}, inplace=True
    )
    grouped["generation_id"] = grouped["generation_id"] + 1

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=grouped["generation_id"],
            y=grouped["Average Fitness"],
            mode="lines+markers",
            name="Average Fitness",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=grouped["generation_id"],
            y=grouped["Best Fitness"],
            mode="lines+markers",
            name="Best Fitness",
        )
    )

    fig.update_layout(
        title="Fitness Performance Over Generations",
        xaxis_title="Generation",
        yaxis_title="Fitness Score",
        hovermode="x unified",
        xaxis={"tickmode": "linear", "tick0": 1, "dtick": 1},
    )
    return fig


def render_fitness_evolution(df):
    st.header("Fitness Score Evolution")
    fig = create_fitness_evolution_plot(df)
    if fig:  # Shaded area
        st.plotly_chart(fig, width="stretch")
    else:
        st.write("Not enough data to plot fitness evolution.")


def create_scenario_distribution_plot(df):
    if df is None or df.empty or "scenario" not in df.columns:
        return None

    fig = px.histogram(
        df, x="scenario", title="Executed Scenarios Frequency", color="scenario"
    )
    fig.update_layout(xaxis_title="Scenario Name", yaxis_title="Execution Count")
    return fig


def render_scenario_distribution(df):
    st.header("Scenario Distribution")
    fig = create_scenario_distribution_plot(df)
    if fig:
        st.plotly_chart(fig, width="stretch")
    else:
        st.write("Not enough data to plot distribution.")


def create_scenario_fitness_variation_plot(df):
    if (
        df is None
        or df.empty
        or "generation_id" not in df.columns
        or "scenario" not in df.columns
    ):
        return None

    # Group by scenario and generation
    grouped = (
        df.groupby(["generation_id", "scenario"])["fitness_score"].max().reset_index()
    )
    if grouped.empty:
        return None

    grouped["generation_id"] = grouped["generation_id"] + 1

    fig = px.line(
        grouped,
        x="generation_id",
        y="fitness_score",
        color="scenario",
        markers=True,
        title="Best Fitness Variation by Scenario",
    )
    fig.update_layout(
        xaxis_title="Generation",
        yaxis_title="Best Fitness Score",
        hovermode="x unified",
        xaxis={"tickmode": "linear", "tick0": 1, "dtick": 1},
    )
    return fig


def render_scenario_fitness_variation(df):
    st.header("Scenario-wise Fitness Variation")
    fig = create_scenario_fitness_variation_plot(df)
    if fig:
        st.plotly_chart(fig, width="stretch")
    else:
        st.write("Not enough data to plot scenario fitness variation.")


def create_baseline_delta_plot(df_all):
    if df_all is None or df_all.empty:
        return None

    score_cols = [
        "fitness_score",
        "health_check_failure_score",
        "health_check_response_time_score",
        "krkn_failure_score",
    ]
    score_labels = {
        "fitness_score": "Fitness",
        "health_check_failure_score": "Health Check Failure Score",
        "health_check_response_time_score": "Health Check Response Time Score",
        "krkn_failure_score": "Krkn Failure Score",
    }

    bl_rows = df_all[df_all["scenario_id"].astype(str) == "baseline"]
    if bl_rows.empty:
        return None

    bl = bl_rows.iloc[0]
    non_bl = df_all[df_all["scenario_id"].astype(str) != "baseline"].copy()
    if non_bl.empty:
        return None

    avail = [c for c in score_cols if c in non_bl.columns]
    if not avail:
        return None

    fig = go.Figure()
    palette = ["#22c55e", "#ef4444", "#a78bfa", "#f97316"]
    for i, col in enumerate(avail):
        bl_val = float(bl[col]) if col in bl.index and not pd.isna(bl[col]) else 0.0
        non_bl[f"delta_{col}"] = non_bl[col].astype(float) - bl_val
        fig.add_trace(
            go.Bar(
                x=non_bl["scenario_id"].astype(str),
                y=non_bl[f"delta_{col}"],
                name=score_labels[col],
                marker_color=palette[i % len(palette)],
                hovertemplate=(
                    f"{score_labels[col]}: %{{y:+.4f}} vs baseline ({bl_val:.4f})"
                    "<extra></extra>"
                ),
            )
        )

    fig.add_hline(
        y=0, line_width=1.5, line_color="#94a3b8", annotation_text="Baseline level"
    )
    fig.update_layout(
        barmode="group",
        title="Score Delta vs Baseline — per Scenario",
        xaxis_title="Scenario ID",
        yaxis_title="Delta (Scenario − Baseline)",
        hovermode="x unified",
        xaxis=dict(type="category"),
        legend_title_text="Score",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=380,
    )
    return fig


def render_baseline_delta(df_all):
    """
    Grouped bar chart showing the delta of each score vs the baseline scenario,
    across all non-baseline scenarios.
    """
    st.header("Score Delta vs Baseline")
    if df_all is None or df_all.empty:
        st.info("No data available.")
        return

    bl_rows = df_all[df_all["scenario_id"].astype(str) == "baseline"]
    if bl_rows.empty:
        st.info("No baseline scenario found — cannot compute deltas.")
        return

    non_bl = df_all[df_all["scenario_id"].astype(str) != "baseline"].copy()
    if non_bl.empty:
        st.info("No non-baseline scenarios to compare.")
        return

    fig = create_baseline_delta_plot(df_all)
    if fig:
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No score columns found.")


def create_improvement_trend_plot(df_all):
    if (
        df_all is None
        or df_all.empty
        or "generation_id" not in df_all.columns
        or "fitness_score" not in df_all.columns
    ):
        return None

    bl_rows = df_all[df_all["scenario_id"].astype(str) == "baseline"]
    if bl_rows.empty:
        return None

    bl_fitness = float(bl_rows.iloc[0]["fitness_score"])
    if bl_fitness == 0:
        return None

    non_bl = df_all[df_all["scenario_id"].astype(str) != "baseline"].copy()
    if non_bl.empty:
        return None

    gen_best = non_bl.groupby("generation_id")["fitness_score"].max().reset_index()
    gen_best["gen_display"] = gen_best["generation_id"] + 1
    gen_best["delta_pct"] = (
        (gen_best["fitness_score"] - bl_fitness) / abs(bl_fitness) * 100
    )

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=gen_best["gen_display"],
            y=gen_best["delta_pct"],
            fill="tozeroy",
            fillcolor="rgba(34,197,94,0.15)",
            line=dict(color="#22c55e", width=2),
            mode="lines+markers",
            marker=dict(
                size=8,
                color=gen_best["delta_pct"].apply(
                    lambda v: "#22c55e" if v >= 0 else "#ef4444"
                ),
            ),
            name="Best Fitness % vs Baseline",
            hovertemplate="Gen %{x}: %{y:+.2f}% vs baseline<extra></extra>",
        )
    )

    # Per-gen avg improvement
    gen_avg = non_bl.groupby("generation_id")["fitness_score"].mean().reset_index()
    if not gen_avg.empty:
        gen_avg["gen_display"] = gen_avg["generation_id"] + 1
        gen_avg["delta_pct"] = (
            (gen_avg["fitness_score"] - bl_fitness) / abs(bl_fitness) * 100
        )
        fig.add_trace(
            go.Scatter(
                x=gen_avg["gen_display"],
                y=gen_avg["delta_pct"],
                mode="lines+markers",
                line=dict(color="#64748b", width=1.5, dash="dot"),
                marker=dict(size=6),
                name="Avg Fitness % vs Baseline",
                hovertemplate="Gen %{x}: avg %{y:+.2f}% vs baseline<extra></extra>",
            )
        )

    fig.add_hline(
        y=0,
        line_color="#06b6d4",
        line_dash="dash",
        annotation_text=f"Baseline ({bl_fitness:.3f})",
    )

    fig.update_layout(
        title="Fitness Improvement vs Baseline — per Generation",
        xaxis_title="Generation",
        yaxis_title="% Improvement vs Baseline",
        hovermode="x unified",
        xaxis=dict(tickmode="linear", tick0=1, dtick=1),
        legend_title_text="Metric",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=350,
    )
    return fig


def render_improvement_trend(df_all):
    """
    Line chart showing per-generation best fitness % improvement vs baseline.
    Positive = better than baseline; negative = worse.
    """
    st.header("Fitness Improvement Trend vs Baseline")
    if (
        df_all is None
        or df_all.empty
        or "generation_id" not in df_all.columns
        or "fitness_score" not in df_all.columns
    ):
        st.info("Not enough data to render improvement trend.")
        return

    bl_rows = df_all[df_all["scenario_id"].astype(str) == "baseline"]
    if bl_rows.empty:
        st.info("No baseline scenario found.")
        return

    bl_fitness = float(bl_rows.iloc[0]["fitness_score"])
    if bl_fitness == 0:
        st.info("Baseline fitness is 0 — cannot compute relative improvement.")
        return

    fig = create_improvement_trend_plot(df_all)
    if fig:
        st.plotly_chart(fig, width="stretch")


def render_generation_details(df, title="Generation & Scenario Details"):
    st.header(title)
    if df is None or df.empty or "generation_id" not in df.columns:
        st.write("No failed scenario details available yet!!")
        return

    # Extract all unique generation numbers for the dropdown
    gen_nums = sorted(df["generation_id"].unique().tolist())
    display_gens = ["All"] + [g + 1 for g in gen_nums]
    selected_gen_disp = st.selectbox(
        "Select Generation to view executed scenarios:", options=display_gens
    )

    if selected_gen_disp == "All":
        st.subheader("Results for All Generations")
        gen_scenarios = df.copy()
    else:
        st.subheader(f"Results for Generation {selected_gen_disp}")
        selected_gen_raw = selected_gen_disp - 1
        gen_scenarios = df[df["generation_id"] == selected_gen_raw].copy()

    if not gen_scenarios.empty:
        # Default sort-- best fitness first (user can click column headers to re-sort)
        gen_scenarios = gen_scenarios.sort_values(by="fitness_score", ascending=False)

        display_cols = [
            "generation_id",
            "scenario_id",
            "scenario",
            "duration_seconds",
            "health_check_failure_score",
            "health_check_response_time_score",
            "krkn_failure_score",
            "fitness_score",
            "parameters",
        ]
        available_cols = [c for c in display_cols if c in gen_scenarios.columns]
        view = gen_scenarios[available_cols].copy()
        if "generation_id" in view.columns:
            view["generation_id"] = view["generation_id"] + 1

        column_cfg = {
            "generation_id": st.column_config.NumberColumn("Generation", format="%d"),
            "scenario_id": st.column_config.NumberColumn("Scenario ID", format="%d"),
            "scenario": st.column_config.TextColumn("Scenario Name", width="medium"),
            "duration_seconds": st.column_config.NumberColumn(
                "Scenario Execution Time (s)", format="%.1f"
            ),
            "health_check_failure_score": st.column_config.NumberColumn(
                "Health Check Failure Score", format="%.4f"
            ),
            "health_check_response_time_score": st.column_config.NumberColumn(
                "Health Check Response Score", format="%.4f"
            ),
            "krkn_failure_score": st.column_config.NumberColumn(
                "Krkn Failure Score", format="%.4f"
            ),
            "fitness_score": st.column_config.NumberColumn(
                "Fitness Score", format="%.4f"
            ),
            "parameters": st.column_config.TextColumn("Parameters"),
        }
        st.dataframe(
            view,
            column_config=column_cfg,
            width="stretch",
            hide_index=True,
        )
    else:
        st.write("No testing details available for this specific generation.")
