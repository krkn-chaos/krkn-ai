import os
import pandas as pd
import yaml
import logging
import glob
import streamlit as st
import re
import json


def load_results_csv(output_dir: str):
    """Return (file_exists, df).  df is None when file is missing or empty or unreadable."""
    csv_path = os.path.join(output_dir, "reports", "all.csv")
    if not os.path.exists(csv_path):
        return False, None
    try:
        df = pd.read_csv(csv_path)
        return True, (None if df.empty else df)
    except Exception as e:
        logging.error(f"Failed to read {csv_path}: {e}")
        return True, None


def load_config_yaml(output_dir: str):
    config_path = os.path.join(output_dir, "krkn-ai.yaml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logging.error(f"Failed to read {config_path}: {e}")
    return None


@st.cache_data(ttl=5)
def load_detailed_scenarios_data(output_dir: str):
    yaml_pattern = os.path.join(output_dir, "yaml", "generation_*", "scenario_*.yaml")
    yaml_files = glob.glob(yaml_pattern)

    rows = []
    for filepath in yaml_files:
        try:
            with open(filepath, "r") as f:
                data = yaml.safe_load(f)

            scen_id = data.get("scenario_id")
            start_time_str = data.get("start_time")
            if not start_time_str or scen_id is None:
                continue

            start_dt = pd.to_datetime(start_time_str)
            hc_results = data.get("health_check_results", {})

            for url, req_list in hc_results.items():
                if not isinstance(req_list, list):
                    continue
                for req in req_list:
                    req_dt = pd.to_datetime(req.get("timestamp"))
                    seconds_into = (req_dt - start_dt).total_seconds()

                    rows.append(
                        {
                            "scenario_id": str(scen_id),
                            "service": req.get("name", "unknown"),
                            "timestamp": req.get("timestamp"),
                            "seconds_into_scenario": seconds_into,
                            "response_time": req.get("response_time"),
                            "status_code": req.get("status_code"),
                            "success": req.get("success"),
                            "error": str(req.get("error"))
                            if req.get("error") is not None
                            else "None",
                        }
                    )
        except Exception as e:
            logging.error(f"Failed to parse {filepath}: {e}")

    if rows:
        df = pd.DataFrame(rows)
        df = df.sort_values(by="seconds_into_scenario")
        return df
    return pd.DataFrame()


def load_health_check_csv(output_dir: str):
    """Return (file_exists, df).  df is None when file is missing or empty or unreadable."""
    csv_path = os.path.join(output_dir, "reports", "health_check_report.csv")
    if not os.path.exists(csv_path):
        return False, None
    try:
        df = pd.read_csv(csv_path)
        return True, (None if df.empty else df)
    except Exception as e:
        logging.error(f"Failed to read {csv_path}: {e}")
        return True, None


# def load_best_scenarios_yaml(output_dir: str):
#     yaml_path = os.path.join(output_dir, "reports", "best_scenarios.yaml")
#     if os.path.exists(yaml_path):
#         try:
#             with open(yaml_path, "r") as f:
#                 return yaml.safe_load(f)
#         except Exception as e:
#             logging.error(f"Failed to load best_scenarios.yaml: {e}")
#     return None


def load_logs(output_dir: str):
    """
    Parse all scenario_N.log files and return a list of structured dicts,
    one per scenario, containing everything needed for the report card.
    """

    log_dir = os.path.join(output_dir, "logs")
    if not os.path.isdir(log_dir):
        return []

    # Matches: "2026-03-17 11:58:12,164 [INFO] message..."
    log_re = re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})(?:,\d+)?\s+\[(?P<level>[A-Z]+)\]\s+(?P<msg>.*)$"
    )
    # Duration line at the end: "container-scenarios ran for 3m12.701171021s"
    duration_re = re.compile(r"^(.+)\s+ran\s+for\s+([\dhms.]+)$")
    # ANSI stripping
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    results = []
    for log_file in sorted(glob.glob(os.path.join(log_dir, "scenario_*.log"))):
        base = os.path.basename(log_file)
        m = re.match(r"scenario_(\d+)\.log", base)
        scen_id = int(m.group(1)) if m else base

        try:
            with open(log_file, "r", errors="replace") as f:
                raw = f.read()
        except Exception as e:
            logging.error(f"Failed to read {log_file}: {e}")
            continue

        lines = raw.splitlines()

        # Environment block
        env_vars: dict = {}
        in_env = False
        for line in lines:
            clean = ansi_re.sub("", line).strip()
            if clean.startswith("Environment Value"):
                in_env = True
                continue
            if in_env:
                parts = clean.split()
                if len(parts) >= 2:
                    env_vars[parts[0]] = parts[1]
                elif not clean:
                    in_env = False

        # Telemetry fields via per-field regex (immune to ASCII art)
        # The Krkn ASCII art banner is printed INSIDE the JSON bloc in some
        # log files, corrupting json.loads.  Extracting individual fields with
        # regexes on the ANSI-stripped raw text is far more robust.
        clean_raw = ansi_re.sub("", raw)

        def jval(key, text=clean_raw):
            """Return the first JSON value for `key` from raw log text."""
            m = re.search(
                r'"' + re.escape(key) + r'"\s*:\s*(.+?)(?:\s*[,\n\r}])', text
            )  # finds that key in raw log text
            if not m:
                return None
            v = m.group(1).strip().strip('"')
            if v == "true":
                return True
            if v == "false":
                return False
            if v == "null":
                return None
            try:
                return json.loads(v)
            except Exception:
                return v

        def jlist(key, text=clean_raw):
            """Return first JSON array value for `key`."""
            m = re.search(r'"' + re.escape(key) + r'"\s*:\s*\[([^\]]*)\]', text)
            if not m:
                return []
            inner = m.group(1)
            try:
                return json.loads("[" + inner + "]")
            except Exception:
                return [x.strip().strip('"') for x in inner.split(",") if x.strip()]

        def jobj(key, text=clean_raw):
            """Return first JSON object for `key` (shallow, no nested braces)."""
            m = re.search(r'"' + re.escape(key) + r'"\s*:\s*\{([^}]*)\}', text)
            if not m:
                return {}
            inner = m.group(1)
            try:
                return json.loads("{" + inner + "}")
            except Exception:
                return {}

        # Top-level telemetry fields
        telemetry = {
            "run_uuid": jval("run_uuid") or "",
            "job_status": jval("job_status"),
            "cluster_version": jval("cluster_version") or "",
            "timestamp": jval("timestamp") or "",
            "total_node_count": jval("total_node_count") or 0,
            "network_plugins": jlist("network_plugins") or ["Unknown"],
            "kubernetes_objects_count": jobj("kubernetes_objects_count"),
            "scenarios": [],
            "node_summary_infos": [],
        }

        # First scenario block (between first "scenarios": [ ... first } ... ])
        scen_m = re.search(r'"scenarios"\s*:\s*\[\s*\{([^}]*)\}', clean_raw)
        first_scen_raw = scen_m.group(1) if scen_m else ""
        telemetry["scenarios"] = [first_scen_raw] if first_scen_raw else []

        # First node_summary_infos block
        node_m = re.search(r'"node_summary_infos"\s*:\s*\[\s*\{([^}]*)\}', clean_raw)
        first_node_raw = node_m.group(1) if node_m else ""

        def node_field(key):
            m = re.search(
                r'"' + re.escape(key) + r'"\s*:\s*"?([^",}\n]+)', first_node_raw
            )
            return m.group(1).strip().strip('"') if m else "—"

        telemetry["node_summary_infos"] = [
            {
                "architecture": node_field("architecture"),
                "os_version": node_field("os_version"),
                "kernel_version": node_field("kernel_version"),
                "kubelet_version": node_field("kubelet_version"),
                "instance_type": node_field("instance_type"),
            }
        ]

        # Structured log lines (timeline)
        timeline = []
        for line in lines:
            m2 = log_re.match(ansi_re.sub("", line))
            if m2:
                timeline.append(
                    {
                        "ts": m2.group("ts").split(" ")[1][:5],  # HH:MM
                        "level": m2.group("level"),
                        "msg": m2.group("msg").strip(),
                    }
                )

        # Duration line
        duration = ""
        scenario_type_from_log = ""
        for line in reversed(lines):
            dm = duration_re.match(line.strip())
            if dm:
                scenario_type_from_log = dm.group(1).strip()
                raw_dur = dm.group(2)
                # Convert e.g. "3m12.701171021s" -> "3m 12s"
                dur_m = re.match(r"(?:(\d+)m)?(?:(\d+)(?:\.\d+)?s)?", raw_dur)
                if dur_m:
                    mins = int(dur_m.group(1) or 0)
                    secs = int(dur_m.group(2) or 0)
                    duration = f"{mins}m {secs}s" if mins else f"{secs}s"
                break

        # Assemble
        # Extract scenario-level fields from the first scenario raw text
        first_scen_raw = (
            telemetry.get("scenarios", [""])[0] if telemetry.get("scenarios") else ""
        )

        def scen_field(key, text=first_scen_raw):
            m = re.search(r'"' + re.escape(key) + r'"\s*:\s*"?([^",}\n]+)', text)
            return m.group(1).strip().strip('"') if m else ""

        scen_type = scen_field("scenario_type") or scenario_type_from_log
        exit_status = scen_field("exit_status")

        # Count affected pods from raw log
        rec_count = len(re.findall(r'"recovered"\s*:\s*\[([^\]]+)\]', clean_raw))
        unrec_count = len(re.findall(r'"unrecovered"\s*:\s*\[([^\]]+)\]', clean_raw))
        # If arrays are empty lists, counts above may be 0

        # Extract scen_params from the nested "parameters" > "scenarios" block
        params_m = re.search(
            r'"parameters"\s*:\s*\{[^}]*"scenarios"\s*:\s*\[\s*\{([^}]+)\}', clean_raw
        )
        params_raw = params_m.group(1) if params_m else first_scen_raw

        def param_field(key, text=params_raw):
            m = re.search(r'"' + re.escape(key) + r'"\s*:\s*"?([^",}\n]+)', text)
            return m.group(1).strip().strip('"') if m else None

        scen_params = {
            "action": param_field("action"),
            "namespace": param_field("namespace"),
            "label_selector": param_field("label_selector"),
            "container_name": param_field("container_name"),
            "count": param_field("count") or param_field("disruption-count"),
            "expected_recovery_time": param_field("expected_recovery_time"),
        }

        node = (
            telemetry.get("node_summary_infos", [{}])[0]
            if telemetry.get("node_summary_infos")
            else {}
        )

        results.append(
            {
                "scenario_id": scen_id,
                "raw_text": raw,
                "run_uuid": telemetry.get("run_uuid", ""),
                "job_status": telemetry.get("job_status", None),
                "cluster_version": telemetry.get("cluster_version", ""),
                "timestamp": telemetry.get("timestamp", ""),
                "total_node_count": telemetry.get("total_node_count", 0),
                "scenario_type": scen_type,
                "exit_status": exit_status,
                "duration": duration,
                "env_vars": env_vars,
                "scen_params": scen_params,
                "affected_recovered": rec_count,
                "affected_unrecovered": unrec_count,
                "node": node,
                "k8s_objects": telemetry.get("kubernetes_objects_count", {}),
                "net_plugins": telemetry.get("network_plugins", ["Unknown"]),
                "timeline": timeline,
            }
        )

    return results
