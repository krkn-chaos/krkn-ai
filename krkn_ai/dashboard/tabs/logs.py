import streamlit as st


@st.dialog("Raw Log File", width="large")
def show_raw_log_modal(raw_text):
    st.code(raw_text, language="log")


def render_logs(log_data, scen_id_to_name=None):
    st.header("Scenario Logs")
    if not log_data:
        st.warning("No log files found in the `logs/` directory.")
        return

    # Scenario selector
    all_ids = [d["scenario_id"] for d in log_data]

    def scen_label(sid):
        if scen_id_to_name:
            name = scen_id_to_name.get(str(sid)) or scen_id_to_name.get(sid)
            if name:
                return f"Scenario {sid} – {name}"
        return f"Scenario {sid}"

    options = [scen_label(s) for s in all_ids]
    id_map = {scen_label(s): s for s in all_ids}

    scen_col, btn_col = st.columns([0.85, 0.15])
    with scen_col:
        chosen = st.selectbox("Select Scenario:", options, key="logs_scen")

    sid = id_map[chosen]
    d = next((x for x in log_data if x["scenario_id"] == sid), {})

    with btn_col:
        st.write("")
        st.write("")
        if st.button("View Raw .log", type="tertiary", use_container_width=True):
            if d:
                show_raw_log_modal(d.get("raw_text", ""))

    if not d:
        st.info("No data for this scenario.")
        return

    job_ok = d.get("job_status") is True
    badge_label = "Job passed" if job_ok else "Job failed"
    run_uuid = d.get("run_uuid", "—")
    ts_raw = d.get("timestamp", "")
    ts_disp = ts_raw.replace("T", " ").replace("Z", " UTC") if ts_raw else "—"

    st.subheader("Krkn chaos run report")
    st.write(f"**Status:** {badge_label} | **UUID:** {run_uuid} | **Time:** {ts_disp}")

    # Top metrics row
    scen_type = d.get("scenario_type", "—")
    cluster_ver = d.get("cluster_version", "—")
    node_cnt = d.get("total_node_count", 0)
    node_info = d.get("node", {})
    arch = node_info.get("architecture", "—")
    os_ver = (node_info.get("os_version") or "—").replace("GNU/Linux ", "")
    exit_st = d.get("exit_status", "—")
    duration = d.get("duration", "—")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Duration", duration, scen_type)
    m2.metric("Cluster version", cluster_ver, "Kubernetes")
    m3.metric("Total nodes", node_cnt, f"{arch} · {os_ver}")
    m4.metric("Scenarios run", 1, f"exit status {exit_st}")

    st.divider()

    # Details anf Affected pods (two columns)
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("### Scenario details")
        params = d.get("scen_params", {}) or {}
        env = d.get("env_vars", {}) or {}

        detail_map = {
            "Type": d.get("scenario_type", env.get("SCENARIO_TYPE", "—")),
            "Action": params.get("action", env.get("ACTION", "—")),
            "Namespace": params.get("namespace", env.get("NAMESPACE", "—")),
            "Label selector": params.get(
                "label_selector", env.get("LABEL_SELECTOR", "—")
            ),
            "Container name": params.get(
                "container_name", env.get("CONTAINER_NAME", "—")
            ),
            "Disruption count": params.get("count", env.get("DISRUPTION_COUNT", "—")),
            "Recovery time": (
                str(
                    params.get(
                        "expected_recovery_time", env.get("EXPECTED_RECOVERY_TIME", "—")
                    )
                )
                + "s"
            ).replace("—s", "—"),
            "Wait duration": (str(env.get("WAIT_DURATION", "—")) + "s").replace(
                "—s", "—"
            ),
        }

        md_table = "| Field | Value |\n|---|---|\n"
        for k, v in detail_map.items():
            if v in (None, "None", "", "—"):
                v = "—"
            md_table += f"| **{k}** | {v} |\n"
        st.markdown(md_table)

    with col_right:
        st.markdown("### Affected pods")
        rec = d.get("affected_recovered", 0)
        unrec = d.get("affected_unrecovered", 0)
        c1, c2 = st.columns(2)
        c1.metric("Recovered", rec)
        c2.metric("Unrecovered", unrec)

        k8s = d.get("k8s_objects", {})
        if k8s:
            st.markdown("### Cluster objects")
            k_cols = st.columns(len(k8s) or 1)
            for col, (k, v) in zip(k_cols, k8s.items()):
                col.metric(f"{k.lower()}s", v)

    st.divider()

    # Node info
    if node_info:
        st.markdown("### Node info")
        net = ", ".join(d.get("net_plugins", ["Unknown"]))
        kubelet = node_info.get("kubelet_version", "—")
        kernel = node_info.get("kernel_version", "—")
        inst = node_info.get("instance_type", "unknown")

        ni1, ni2, ni3 = st.columns(3)
        ni1.metric("Architecture", arch)
        ni2.metric("OS", os_ver)
        ni3.metric("Kernel", kernel)

        ni4, ni5, ni6 = st.columns(3)
        ni4.metric("Kubelet", kubelet)
        ni5.metric("Instance type", inst)
        ni6.metric("Network plugin", net)

    # Run Timeline
    timeline = d.get("timeline", [])
    if timeline:
        st.markdown("### Run timeline")

        SKIP_FRAGS = ["✅ type:", "✅ types:"]
        key_lines = [t for t in timeline if not any(f in t["msg"] for f in SKIP_FRAGS)]

        tl_text = ""
        for item in key_lines:
            ts = item["ts"]
            level = item["level"]
            msg = item["msg"]
            tl_text += f"{ts}  [{level}]  {msg}\n"

        with st.expander("View Timeline", expanded=True):
            st.code(tl_text, language="log")
