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


def render_fitness_evolution(df):
    st.header("Fitness Score Evolution")
    if df is None or df.empty or "generation_id" not in df.columns:
        st.write("Not enough data to plot fitness evolution.")
        return

    # Grouping CSV by generation to plot Best vs Average
    grouped = (
        df.groupby("generation_id")["fitness_score"].agg(["mean", "max"]).reset_index()
    )
    grouped.rename(
        columns={"mean": "Average Fitness", "max": "Best Fitness"}, inplace=True
    )
    grouped["generation_id"] = grouped["generation_id"] + 1

    if not grouped.empty:
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
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No fitness scores recorded yet.")


def render_scenario_distribution(df):
    st.header("Scenario Distribution")
    if df is None or df.empty or "scenario" not in df.columns:
        st.write("Not enough data to plot distribution.")
        return

    fig = px.histogram(
        df, x="scenario", title="Executed Scenarios Frequency", color="scenario"
    )
    fig.update_layout(xaxis_title="Scenario Name", yaxis_title="Execution Count")
    st.plotly_chart(fig, use_container_width=True)


def render_scenario_fitness_variation(df):
    st.header("Scenario-wise Fitness Variation")
    if (
        df is None
        or df.empty
        or "generation_id" not in df.columns
        or "scenario" not in df.columns
    ):
        st.write("Not enough data to plot scenario fitness variation.")
        return

    # Group by scenario and generation
    grouped = (
        df.groupby(["generation_id", "scenario"])["fitness_score"].max().reset_index()
    )
    grouped["generation_id"] = grouped["generation_id"] + 1

    if not grouped.empty:
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
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data points yet.")


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
                "Duration (s)", format="%.1f"
            ),
            "health_check_failure_score": st.column_config.NumberColumn(
                "HC Failure Score", format="%.4f"
            ),
            "health_check_response_time_score": st.column_config.NumberColumn(
                "HC Response Score", format="%.4f"
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
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.write("No testing details available for this specific generation.")
