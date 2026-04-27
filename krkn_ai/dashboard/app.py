import os
import argparse
import time
import json
from typing import Optional
import pandas as pd
import streamlit as st
from krkn_ai.constants import (
    STATUS_STARTED,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_FAILED,
)
from krkn_ai.dashboard.data_loader import (
    load_results_csv,
    load_config_yaml,
    load_health_check_csv,
    load_detailed_scenarios_data,
    load_logs,
)
from krkn_ai.dashboard.tabs.dashboard import (
    render_summary,
    render_fitness_evolution,
    render_scenario_distribution,
    render_scenario_fitness_variation,
    render_generation_details,
)
from krkn_ai.dashboard.tabs.health_checks import render_health_checks
from krkn_ai.dashboard.tabs.detailed_scenarios import render_detailed_scenarios
from krkn_ai.dashboard.tabs.logs import render_logs
from krkn_ai.dashboard.tabs.config import render_config


def get_monitor_config():
    """Retrieve monitor config from command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=str, default="./")
    try:
        args, _ = parser.parse_known_args()
        return {"output_dir": args.output_dir}
    except SystemExit:
        return {"output_dir": "./"}


def is_execution_running(output_dir: str) -> bool:
    """Detect if krkn-ai is currently running by checking results.json."""
    results_file = os.path.join(output_dir, "results.json")
    if not os.path.exists(results_file):
        return False
    try:
        with open(results_file, "r") as f:
            data = json.load(f)
            status = data.get("status")
            if status in [STATUS_STARTED, STATUS_IN_PROGRESS]:
                return True
    except Exception:
        pass
    return False


def get_run_status(output_dir: str) -> Optional[str]:
    """Return the raw status string from results.json, or None if unavailable."""
    results_file = os.path.join(output_dir, "results.json")
    if not os.path.exists(results_file):
        return None
    try:
        with open(results_file, "r") as f:
            data = json.load(f)
            return data.get("status")
    except Exception:
        return None


def main():
    st.set_page_config(page_title="Krkn-AI Monitor", layout="wide")
    st.title("Krkn-AI Execution Monitor")

    monitor_config = get_monitor_config()
    base_output_dir = monitor_config.get("output_dir", "./")

    run_dirs = []
    if os.path.exists(base_output_dir) and os.path.isdir(base_output_dir):
        # Determine if base_output_dir is a parent folder mapping to UUIDs
        for item in os.listdir(base_output_dir):
            full_path = os.path.join(base_output_dir, item)
            if os.path.isdir(full_path):
                # A run directory will typically contain results.json or config.yaml
                if os.path.exists(
                    os.path.join(full_path, "results.json")
                ) or os.path.exists(os.path.join(full_path, "krkn-ai.yaml")):
                    run_dirs.append(item)

    if run_dirs:
        # Sort by latest modified
        run_dirs.sort(
            key=lambda x: os.path.getmtime(os.path.join(base_output_dir, x)),
            reverse=True,
        )
        st.sidebar.header("Select Run")
        selected_uuid = st.sidebar.selectbox("Run UUID:", run_dirs)
        output_dir = os.path.join(base_output_dir, selected_uuid)
        st.sidebar.divider()
    else:
        output_dir = base_output_dir

    # Detect state purely from results.json
    running = is_execution_running(output_dir)
    run_status = get_run_status(output_dir)

    st.sidebar.header("Controls")
    if running:
        st.sidebar.info("Execution in progress...")
        auto_refresh = True
    elif run_status == STATUS_FAILED:
        st.sidebar.error("Execution failed!")
        auto_refresh = False
    elif run_status == STATUS_COMPLETED:
        st.sidebar.success("Execution completed!")
        auto_refresh = False
    else:
        st.sidebar.warning("Execution status unknown.")
        auto_refresh = False

    # Load data — loaders return (file_found: bool, df | None)
    results_file_found, df_results = load_results_csv(output_dir)
    config_data = load_config_yaml(output_dir)
    health_file_found, df_health = load_health_check_csv(output_dir)
    df_details = load_detailed_scenarios_data(output_dir)
    df_logs = load_logs(output_dir)

    # results_empty_file / health_empty_file - file exists but df is None (empty CSV)
    results_empty_file = results_file_found and df_results is None
    health_empty_file = health_file_found and df_health is None

    # Detect completely invalid / non-result folder- no data files found anywhere
    has_any_data = (
        df_results is not None
        or df_health is not None
        or (df_details is not None and not df_details.empty)
        or bool(df_logs)
        or config_data is not None
    )

    # Build scenario_id -> scenario_name lookup from results
    scen_id_to_name = {}
    if (
        df_results is not None
        and not df_results.empty
        and "scenario_id" in df_results.columns
        and "scenario" in df_results.columns
    ):
        for _, row in (
            df_results[["scenario_id", "scenario"]].drop_duplicates().iterrows()
        ):
            sid = row["scenario_id"]
            scen_id_to_name[str(sid)] = row["scenario"]
            try:
                sid_int = int(float(sid))
                scen_id_to_name[str(sid_int)] = row["scenario"]
                scen_id_to_name[sid_int] = row["scenario"]
            except (ValueError, TypeError):
                pass

    # Global Filters
    st.sidebar.header("Global Filters")

    # Collect all known scenario names, IDs and generations (from results CSV)
    all_scenario_names = []
    all_scenario_ids = []
    all_generations = []
    if df_results is not None and not df_results.empty:
        if "scenario" in df_results.columns:
            all_scenario_names = sorted(df_results["scenario"].unique().tolist())
        if "scenario_id" in df_results.columns:

            def safe_cast(v):
                try:
                    return int(float(v))
                except (ValueError, TypeError):
                    return str(v)

            raw_ids = df_results["scenario_id"].dropna().unique()
            sorted_raw = sorted(
                raw_ids, key=lambda x: (isinstance(safe_cast(x), str), safe_cast(x))
            )
            all_scenario_ids = [safe_cast(x) for x in sorted_raw]
        if "generation_id" in df_results.columns:
            all_generations = sorted(
                [int(x) + 1 for x in df_results["generation_id"].dropna().unique()]
            )

    global_generations = st.sidebar.multiselect(
        "Filter by Generation:",
        options=all_generations,
        default=[],
        help="Leave empty to show all generations across every tab.",
    )

    global_scenarios_name = st.sidebar.multiselect(
        "Filter by Scenario Name:",
        options=all_scenario_names,
        default=[],
        help="Leave empty to show all scenarios across every tab.",
    )

    global_scenarios_id = st.sidebar.multiselect(
        "Filter by Scenario Number:",
        options=all_scenario_ids,
        default=[],
        help="Leave empty to show all scenarios across every tab.",
    )

    # Collect all known services (from health-check CSV + detailed scenarios)
    all_services = set()
    if (
        df_health is not None
        and not df_health.empty
        and "component_name" in df_health.columns
    ):
        all_services.update(df_health["component_name"].unique().tolist())
    if (
        df_details is not None
        and not df_details.empty
        and "service" in df_details.columns
    ):
        all_services.update(df_details["service"].unique().tolist())
    all_services = sorted(all_services)

    global_services = st.sidebar.multiselect(
        "Filter by Service:",
        options=all_services,
        default=[],
        help="Leave empty to show all services across every tab.",
    )

    # Best Iterations Scope
    filter_type = "All"
    SCORE_COLS = [
        "fitness_score",
        "health_check_failure_score",
        "health_check_response_time_score",
        "krkn_failure_score",
    ]
    if df_results is not None and not df_results.empty:
        st.sidebar.subheader("Best Iterations Scope")
        available_score_cols = [c for c in SCORE_COLS if c in df_results.columns]
        sort_col = st.sidebar.selectbox(
            "Sort by:",
            options=available_score_cols,
            format_func=lambda c: {
                "fitness_score": "Fitness Score",
                "health_check_failure_score": "Health Check Failure Score",
                "health_check_response_time_score": "Health Check Response Time Score",
                "krkn_failure_score": "Krkn Failure Score",
            }.get(c, c),
            key="best_iter_sort_col",
        )
        filter_type = st.sidebar.radio(
            "Filter Generator Rows:",
            [
                "All",
                "Top K scenarios by above score",
                "Top P(%) scenarios by above score",
            ],
        )

        if filter_type == "Top K scenarios by above score":
            k_value = st.sidebar.number_input(
                "Top K count:", min_value=1, value=3, step=1
            )
            df_results = df_results.sort_values(by=sort_col, ascending=False).head(
                int(k_value)
            )
        elif filter_type == "Top P(%) scenarios by above score":
            p_value = st.sidebar.slider(
                "Top Percentage (%):", min_value=1, max_value=100, value=25
            )
            cutoff = max(1, int(len(df_results) * (p_value / 100.0)))
            df_results = df_results.sort_values(by=sort_col, ascending=False).head(
                cutoff
            )

    # df_results_all = df_results  # keeping a reference to unfiltered dataframe if needed later!!
    df_failed = None
    if df_results is not None and not df_results.empty:
        # Separating failed scenarios.
        # If krkn_failure_score < 0, it's considered a misconfiguration or krkn engine failure.
        if "krkn_failure_score" in df_results.columns:
            # krkn_failure_score < 0 means krkn engine failed / misconfiguration
            mask_failed = df_results["krkn_failure_score"] < 0
            df_failed = df_results[mask_failed]
            df_results = df_results[~mask_failed]
        else:
            df_failed = pd.DataFrame()

    # Apply global scenario filters to results
    active_scenario_names = (
        global_scenarios_name if global_scenarios_name else all_scenario_names
    )
    active_scenario_ids = (
        global_scenarios_id if global_scenarios_id else all_scenario_ids
    )
    active_generations = global_generations if global_generations else all_generations

    if df_results is not None and not df_results.empty:
        if active_scenario_names:
            df_results = df_results[df_results["scenario"].isin(active_scenario_names)]
        if active_scenario_ids:
            str_ids = [str(x) for x in active_scenario_ids]
            df_results = df_results[df_results["scenario_id"].astype(str).isin(str_ids)]
        if active_generations and "generation_id" in df_results.columns:
            df_results = df_results[
                (df_results["generation_id"] + 1).isin(active_generations)
            ]

    if df_failed is not None and not df_failed.empty:
        if active_scenario_names:
            df_failed = df_failed[df_failed["scenario"].isin(active_scenario_names)]
        if active_scenario_ids:
            str_ids = [str(x) for x in active_scenario_ids]
            df_failed = df_failed[df_failed["scenario_id"].astype(str).isin(str_ids)]
        if active_generations and "generation_id" in df_failed.columns:
            df_failed = df_failed[
                (df_failed["generation_id"] + 1).isin(active_generations)
            ]

    # Derive the filtered scenario IDs for cross-tab consistency (from successful runs only)
    filtered_scenario_ids = (
        df_results["scenario_id"].unique().tolist()
        if df_results is not None
        and not df_results.empty
        and "scenario_id" in df_results.columns
        else []
    )

    # Filter flag
    filters_active = bool(
        global_scenarios_name or global_scenarios_id or global_generations
    )

    # Apply global scenario filter to health-check CSV
    if df_health is not None and not df_health.empty and filters_active:
        str_ids = [str(x) for x in filtered_scenario_ids]
        df_health = df_health[df_health["scenario_id"].astype(str).isin(str_ids)]

    # Apply global scenario filter to detailed scenarios CSV (scenario_id stored as str there)
    if df_details is not None and not df_details.empty and filters_active:
        str_ids = [str(x) for x in filtered_scenario_ids]
        df_details = df_details[df_details["scenario_id"].astype(str).isin(str_ids)]

    # Tabs
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "Dashboard",
            "Health Checks",
            "Detailed Scenarios",
            "Logs",
            "Configuration",
            "Failed Scenarios",
        ]
    )

    with tab1:
        if not has_any_data:
            st.warning(
                f"The selected folder **`{output_dir}`** does not appear to be a valid "
                f"Krkn-AI result directory. No recognised data files were found."
            )
        elif results_empty_file:
            st.info(
                "`reports/all.csv` exists but is empty, no scenario results have been recorded yet."
            )
        elif df_results is None:
            st.info(
                "No scenario results file found yet. Waiting for the run to produce `reports/all.csv`…"
            )
        elif filters_active and df_results.empty:
            st.warning(
                "No scenarios match the selected filters. Try adjusting the sidebar filters."
            )
        else:
            render_summary(df_results)
            st.divider()

            colA, colB = st.columns(2)
            with colA:
                render_scenario_distribution(df_results)
            with colB:
                render_scenario_fitness_variation(df_results)

            st.divider()
            render_fitness_evolution(df_results)
            st.divider()
            render_generation_details(df_results)

    with tab2:
        if not has_any_data:
            st.warning("No valid Krkn-AI data found in the selected folder.")
        elif health_empty_file:
            st.info("`reports/health_check_report.csv` exists but is empty.")
        elif df_health is None:
            st.info("No health check data found yet.")
        elif filters_active and (df_health is None or df_health.empty):
            st.warning(
                "No health-check data matches the selected filters. Try adjusting the sidebar filters."
            )
        else:
            render_health_checks(
                df_health, global_services=global_services if global_services else None
            )

    with tab3:
        if not has_any_data:
            st.warning("No valid Krkn-AI data found in the selected folder.")
        elif filters_active and (df_details is None or df_details.empty):
            st.warning(
                "No detailed scenario telemetry matches the selected filters. Try adjusting the sidebar filters."
            )
        else:
            render_detailed_scenarios(
                df_details,
                global_scenarios=filtered_scenario_ids
                if filtered_scenario_ids
                else None,
                global_services=global_services if global_services else None,
                scen_id_to_name=scen_id_to_name,
            )

    with tab4:
        render_logs(df_logs, scen_id_to_name=scen_id_to_name)

    with tab5:
        render_config(config_data)

    with tab6:
        render_generation_details(df_failed, title="Failed Scenarios")

    # Refresh mechanism
    if auto_refresh:
        time.sleep(3)
        st.rerun()


if __name__ == "__main__":
    main()
