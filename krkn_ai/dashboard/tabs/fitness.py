import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from krkn_ai.dashboard.data_loader import map_slo_columns, slo_columns

MAX_BAR_SCENARIOS = 30


def query_color_map(names):
    """Fix a colour per query so it stays the same across every chart on the tab."""
    palette = px.colors.qualitative.Plotly
    return {
        name: palette[i % len(palette)] for i, name in enumerate(sorted(set(names)))
    }


def build_contribution_frame(df, items):
    """One row per scenario and query, with what that query added to the score."""
    if df is None or df.empty or not items:
        return pd.DataFrame()

    mapping = map_slo_columns(items, df.columns)
    if not mapping:
        return pd.DataFrame()

    rows = []
    for _, row in df.iterrows():
        for col, item in mapping.items():
            value = row.get(col)
            if pd.isna(value):
                continue
            weighted = row.get(f"{col}_weighted")
            rows.append(
                {
                    "scenario_id": str(row.get("scenario_id", "?")),
                    "scenario": row.get("scenario", "?"),
                    "generation_id": row.get("generation_id"),
                    "name": item["name"],
                    "category": item["category"] or "—",
                    "query": item["query"],
                    "weight": item["weight"],
                    "raw": float(value),
                    "contribution": float(weighted)
                    if pd.notna(weighted)
                    else float(value) * item["weight"],
                }
            )
    return pd.DataFrame(rows)


def create_contribution_plot(long_df):
    """Stacked bar of what each query contributed to every scenario's fitness."""
    if long_df is None or long_df.empty:
        return None

    totals = (
        long_df.groupby("scenario_id")["contribution"]
        .sum()
        .sort_values(ascending=False)
    )
    keep = totals.head(MAX_BAR_SCENARIOS).index.tolist()
    working = long_df[long_df["scenario_id"].isin(keep)]

    fig = px.bar(
        working,
        x="scenario_id",
        y="contribution",
        color="name",
        title="Fitness Contribution by Query",
        hover_data=["category", "raw", "weight"],
        color_discrete_map=query_color_map(long_df["name"]),
    )
    fig.update_layout(
        barmode="relative",
        xaxis_title="Scenario ID",
        yaxis_title="Weighted Contribution",
        xaxis=dict(type="category", categoryorder="array", categoryarray=keep),
        legend_title_text="Query",
        hovermode="x unified",
        height=420,
    )
    return fig


def create_query_evolution_plot(long_df, names=None):
    """Mean raw value per generation, one line per query."""
    if long_df is None or long_df.empty or "generation_id" not in long_df.columns:
        return None

    colors = query_color_map(long_df["name"])

    working = long_df.dropna(subset=["generation_id"])
    if names:
        working = working[working["name"].isin(names)]
    if working.empty:
        return None

    grouped = working.groupby(["generation_id", "name"])["raw"].mean().reset_index()
    grouped["generation_id"] = grouped["generation_id"] + 1

    fig = px.line(
        grouped,
        x="generation_id",
        y="raw",
        color="name",
        markers=True,
        title="Query Value Over Generations",
        color_discrete_map=colors,
    )
    fig.update_layout(
        xaxis_title="Generation",
        yaxis_title="Mean Raw Value",
        xaxis={"tickmode": "linear", "tick0": 1, "dtick": 1},
        legend_title_text="Query",
        hovermode="x unified",
        height=380,
    )
    return fig


def build_query_summary(long_df):
    """Per-query stats, flagging the queries that never moved across scenarios."""
    if long_df is None or long_df.empty:
        return pd.DataFrame()

    summary = (
        long_df.groupby(["name", "category", "weight"])
        .agg(
            mean_value=("raw", "mean"),
            max_value=("raw", "max"),
            spread=("raw", lambda s: float(s.max() - s.min())),
            mean_contribution=("contribution", "mean"),
        )
        .reset_index()
    )
    summary["flat"] = summary["spread"] == 0
    return summary.sort_values(by="mean_contribution", ascending=False)


def build_weights_frame(items, learned_weights):
    """Configured weight next to the weight this run learned, per query."""
    learned_weights = learned_weights or {}
    rows = []
    for item in items:
        if not item["enabled"]:
            continue
        learned = learned_weights.get(item["query"])
        rows.append(
            {
                "name": item["name"],
                "configured": item["weight"],
                "learned": learned,
                "delta": None if learned is None else learned - item["weight"],
                "query": item["query"],
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty or frame["learned"].isna().all():
        return frame
    return frame.sort_values(by="learned", ascending=False)


def build_rejected_frame(items):
    """The queries discover would not run, with the reason it gave."""
    return pd.DataFrame(
        [
            {"name": item["name"], "reason": item["reason"], "query": item["query"]}
            for item in items
            if not item["enabled"]
        ]
    )


def create_weights_plot(weights_df):
    """Configured vs learned weight, side by side."""
    if weights_df is None or weights_df.empty or weights_df["learned"].isna().all():
        return None

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=weights_df["name"],
            y=weights_df["configured"],
            name="Configured",
            marker_color="#64748b",
        )
    )
    fig.add_trace(
        go.Bar(
            x=weights_df["name"],
            y=weights_df["learned"],
            name="Learned",
            marker_color="#22c55e",
        )
    )
    fig.update_layout(
        barmode="group",
        title="Configured vs Learned Weights",
        xaxis_title="Query",
        yaxis_title="Weight",
        legend_title_text="Source",
        height=380,
    )
    return fig


def render_fitness(df, items, learned_weights=None, output_dir=None):
    st.header("Fitness Breakdown")

    if not items:
        st.info(
            "No per-query fitness items in this run's config. The run used a single "
            "`fitness_function.query`, so there is nothing to break down."
        )
        return

    enabled = [item for item in items if item["enabled"]]
    disabled = [item for item in items if not item["enabled"]]

    cols = st.columns(3)
    cols[0].metric("Queries In Use", len(enabled))
    cols[1].metric("Queries Rejected", len(disabled))
    cols[2].metric("Total Weight", f"{sum(item['weight'] for item in enabled):.4f}")

    long_df = build_contribution_frame(df, items)
    if long_df.empty and df is not None and not df.empty:
        present = len(slo_columns(df.columns))
        if present and present != len(enabled):
            st.warning(
                f"`reports/all.csv` has {present} per-query columns but the config "
                f"lists {len(enabled)} items — they were written by a different "
                "config, so the breakdown is skipped to avoid mislabelling."
            )
        else:
            st.info("No per-query scores recorded yet.")

    if not long_df.empty:
        st.divider()
        fig = create_contribution_plot(long_df)
        if fig:
            st.plotly_chart(fig, width="stretch")
            total_scenarios = long_df["scenario_id"].nunique()
            if total_scenarios > MAX_BAR_SCENARIOS:
                st.caption(
                    f"Showing the top {MAX_BAR_SCENARIOS} scenarios by total "
                    f"contribution out of {total_scenarios}."
                )

        st.divider()
        st.subheader("Query Statistics")
        summary = build_query_summary(long_df)
        st.dataframe(
            summary,
            column_config={
                "name": st.column_config.TextColumn("Query", width="medium"),
                "category": st.column_config.TextColumn("Category"),
                "weight": st.column_config.NumberColumn("Weight", format="%.4f"),
                "mean_value": st.column_config.NumberColumn("Mean", format="%.4f"),
                "max_value": st.column_config.NumberColumn("Max", format="%.4f"),
                "spread": st.column_config.NumberColumn("Spread", format="%.4f"),
                "mean_contribution": st.column_config.NumberColumn(
                    "Mean Contribution", format="%.4f"
                ),
                "flat": st.column_config.CheckboxColumn("Flat"),
            },
            width="stretch",
            hide_index=True,
        )
        flat = summary[summary["flat"]]["name"].tolist()
        if flat:
            st.caption(
                "Flat queries returned the same value for every scenario and are "
                f"not steering the search: {', '.join(flat)}."
            )

        st.divider()
        st.subheader("Query Evolution")
        options = sorted(long_df["name"].unique().tolist())
        selected = st.multiselect(
            "Queries to plot:",
            options=options,
            default=options[:5],
            help="Mean raw value per generation, before weighting.",
        )
        evo = create_query_evolution_plot(long_df, selected)
        if evo:
            st.plotly_chart(evo, width="stretch")
        else:
            st.write("Select at least one query to plot.")

    st.divider()
    render_weights(items, learned_weights, output_dir)

    if disabled:
        st.divider()
        st.subheader("Queries Discover Rejected")
        st.dataframe(
            build_rejected_frame(items),
            column_config={
                "name": st.column_config.TextColumn("Query", width="medium"),
                "reason": st.column_config.TextColumn("Reason", width="medium"),
                "query": st.column_config.TextColumn("PromQL", width="large"),
            },
            width="stretch",
            hide_index=True,
        )


def render_weights(items, learned_weights=None, output_dir=None):
    st.subheader("Fitness Weights")
    weights_df = build_weights_frame(items, learned_weights)
    if weights_df.empty:
        st.info("No weighted fitness items in this run.")
        return

    if weights_df["learned"].isna().all():
        st.info(
            "No `learned_weights.json` in this run directory — it is written when "
            "a run finishes with per-query fitness items."
        )
        st.dataframe(
            weights_df[["name", "configured", "query"]],
            column_config={
                "name": st.column_config.TextColumn("Query", width="medium"),
                "configured": st.column_config.NumberColumn(
                    "Configured", format="%.4f"
                ),
                "query": st.column_config.TextColumn("PromQL", width="large"),
            },
            width="stretch",
            hide_index=True,
        )
        return

    fig = create_weights_plot(weights_df)
    if fig:
        st.plotly_chart(fig, width="stretch")

    st.dataframe(
        weights_df,
        column_config={
            "name": st.column_config.TextColumn("Query", width="medium"),
            "configured": st.column_config.NumberColumn("Configured", format="%.4f"),
            "learned": st.column_config.NumberColumn("Learned", format="%.4f"),
            "delta": st.column_config.NumberColumn("Delta", format="%+.4f"),
            "query": st.column_config.TextColumn("PromQL", width="large"),
        },
        width="stretch",
        hide_index=True,
    )
    st.caption(
        "Learned weights favour the queries that discriminated most between "
        "scenarios. Feed them into the next discover run:"
    )
    st.code(
        "krkn_ai discover --learned-weights "
        f"{output_dir or '<run-dir>'}/learned_weights.json --save-strategy merge",
        language="bash",
    )
