"""
Evolutionary Lineage Tab for Krkn-AI Dashboard.

Shows how scenarios evolved across generations:
  1. Origin distribution — donut chart of crossover / composition / mutation / initial.
  2. Per-generation origin breakdown — stacked bar showing GA strategy over time.
  3. Lineage explorer — trace a selected scenario back to its ancestors.
"""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


_ORIGIN_COLORS = {
    "initial": "#64748b",
    "crossover": "#3b82f6",
    "composition": "#8b5cf6",
    "parameter_mutation": "#f59e0b",
    "type_mutation": "#ef4444",
}

_ORIGIN_LABELS = {
    "initial": "Initial",
    "crossover": "Crossover",
    "composition": "Composition",
    "parameter_mutation": "Param Mutation",
    "type_mutation": "Type Mutation",
}


def render_lineage(df_lineage):
    st.header("Evolutionary Lineage")

    if df_lineage is None or df_lineage.empty:
        st.info("No lineage data available for this run.")
        return

    has_origin = "origin" in df_lineage.columns and df_lineage["origin"].notna().any()
    if not has_origin:
        st.info("Lineage origin data not recorded for this run.")
        return

    col_a, col_b = st.columns(2)
    with col_a:
        _render_origin_distribution(df_lineage)
    with col_b:
        _render_generation_breakdown(df_lineage)

    st.divider()
    _render_lineage_explorer(df_lineage)


def _render_origin_distribution(df):
    counts = df["origin"].value_counts()
    labels = [_ORIGIN_LABELS.get(o, o) for o in counts.index]
    colors = [_ORIGIN_COLORS.get(o, "#94a3b8") for o in counts.index]

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=counts.values,
            hole=0.45,
            marker=dict(colors=colors),
            textinfo="label+percent",
            hovertemplate="%{label}: %{value} scenarios (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(
        title="Origin Distribution",
        showlegend=False,
        height=350,
        margin=dict(t=40, b=20, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_generation_breakdown(df):
    if "generation" not in df.columns:
        st.write("No generation data available.")
        return

    grouped = df.groupby(["generation", "origin"]).size().reset_index(name="count")
    grouped["generation_display"] = grouped["generation"] + 1
    grouped["origin_label"] = grouped["origin"].map(lambda o: _ORIGIN_LABELS.get(o, o))

    color_map = {_ORIGIN_LABELS.get(k, k): v for k, v in _ORIGIN_COLORS.items()}

    fig = px.bar(
        grouped,
        x="generation_display",
        y="count",
        color="origin_label",
        color_discrete_map=color_map,
        title="GA Strategy per Generation",
        labels={
            "generation_display": "Generation",
            "count": "Scenarios",
            "origin_label": "Origin",
        },
    )
    fig.update_layout(
        barmode="stack",
        xaxis=dict(tickmode="linear", tick0=1, dtick=1),
        height=350,
        margin=dict(t=40, b=20, l=20, r=20),
        legend_title_text="Origin",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_lineage_explorer(df):
    st.subheader("Lineage Explorer")

    if "scenario_uuid" not in df.columns or "parent_ids" not in df.columns:
        st.info("Scenario UUID data not available for lineage tracing.")
        return

    uuid_to_row = {}
    for _, row in df.iterrows():
        uid = row.get("scenario_uuid")
        if uid:
            uuid_to_row[uid] = row

    sorted_df = df.sort_values("fitness_score", ascending=False)
    options = []
    option_map = {}
    for _, row in sorted_df.iterrows():
        sid = row.get("scenario_id", "?")
        gen = row.get("generation", "?")
        score = row.get("fitness_score", 0)
        uid = row.get("scenario_uuid", "")
        label = f"Scenario {sid} (Gen {int(gen) + 1}, Fitness {score:.2f})"
        options.append(label)
        option_map[label] = uid

    if not options:
        st.info("No scenarios to explore.")
        return

    selected = st.selectbox("Select a scenario to trace its lineage:", options)
    selected_uuid = option_map.get(selected)
    if not selected_uuid:
        return

    chain = _build_ancestry_chain(selected_uuid, uuid_to_row)

    if len(chain) <= 1:
        st.caption("This is an initial scenario with no ancestors.")

    for i, node in enumerate(chain):
        origin = node.get("origin", "unknown")
        origin_label = _ORIGIN_LABELS.get(origin, origin or "—")
        gen = node.get("generation", "?")
        gen_display = int(gen) + 1 if gen != "?" else "?"
        score = node.get("fitness_score", 0)
        sid = node.get("scenario_id", "?")

        prefix = "**Selected** | " if i == 0 else ""
        parents = node.get("parent_ids", [])
        parent_hint = ""
        if parents and isinstance(parents, list) and len(parents) > 0:
            parent_sids = []
            for pid in parents:
                prow = uuid_to_row.get(pid)
                if prow is not None:
                    parent_sids.append(str(prow.get("scenario_id", pid[:8])))
                else:
                    parent_sids.append(pid[:8] + "...")
            parent_hint = f" | Parents: {', '.join(parent_sids)}"

        st.markdown(
            f":{_origin_to_streamlit_color(origin)}[**Gen {gen_display}**] "
            f"{prefix}Scenario {sid} — "
            f"Fitness **{score:.2f}** — "
            f"Origin: {origin_label}{parent_hint}"
        )

        if i < len(chain) - 1:
            st.markdown(
                "<div style='border-left: 2px solid #475569; height: 16px; "
                "margin-left: 24px;'></div>",
                unsafe_allow_html=True,
            )


def _build_ancestry_chain(start_uuid, uuid_to_row, max_depth=20):
    chain = []
    current = start_uuid
    visited = set()

    for _ in range(max_depth):
        if current in visited or current not in uuid_to_row:
            break
        visited.add(current)
        row = uuid_to_row[current]
        chain.append(row.to_dict())

        parents = row.get("parent_ids", [])
        if not parents or not isinstance(parents, list) or len(parents) == 0:
            break
        current = parents[0]

    return chain


def _origin_to_streamlit_color(origin):
    return {
        "initial": "gray",
        "crossover": "blue",
        "composition": "violet",
        "parameter_mutation": "orange",
        "type_mutation": "red",
    }.get(origin, "gray")
