import os
import pandas as pd
import yaml
import logging
import glob
import streamlit as st
import re
import json

from typing import List

from krkn_ai.models.config import OutputConfig
from krkn_ai.utils.output import fmt_to_glob, fmt_to_id_regex
from krkn_ai.utils.weight_learning import load_learned_weights as read_learned_weights

LEARNED_WEIGHTS_FILE = "learned_weights.json"

_SLO_RE = re.compile(r"^slo_\d+$")
_COMMENT_MARKER_RE = re.compile(r"^#\s?")
_TOP_KEY_RE = re.compile(r"^[A-Za-z_][\w-]*:")
_QUERY_RE = re.compile(r"^-\s*query:\s*(?P<query>.+?)\s*$")
_TYPE_RE = re.compile(r"^type:\s*(?P<type>\w+)\s*$")
_NAME_RE = re.compile(r"^(?P<name>\S+?)(?:\s*\((?P<reason>.*)\))?$")
_INLINE_DISABLED_RE = re.compile(
    r"^(?P<name>\S+)\s*\((?P<reason>.*?)\):\s*(?P<query>.+?)\s*$"
)
_HC_REASON_RE = re.compile(r"^\((?P<reason>[^)]*)\)$")
_HC_NAME_RE = re.compile(r"^-\s*name:\s*(?P<name>.+?)\s*$")
_HC_URL_RE = re.compile(r"^url:\s*(?P<url>.+?)\s*$")

_CATALOG_MATCHERS = None


def _unquote(value: str) -> str:
    return (value or "").strip().strip("'\"")


def _short_query(query: str, width: int = 60) -> str:
    query = (query or "").strip()
    return query if len(query) <= width else f"{query[: width - 1]}…"


@st.cache_data(ttl=300)
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


@st.cache_data(ttl=300)
def load_population_lineage(output_dir: str):
    """Load population_lineage from results.json. Returns a DataFrame or None."""
    results_path = os.path.join(output_dir, "results.json")
    if not os.path.exists(results_path):
        return None
    try:
        with open(results_path, "r") as f:
            data = json.load(f)
        lineage = data.get("population_lineage")
        if not lineage:
            return None
        df = pd.DataFrame(lineage)
        if df.empty or "origin" not in df.columns:
            return None
        return df
    except Exception as e:
        logging.error(f"Failed to load lineage from {results_path}: {e}")
        return None


@st.cache_data(ttl=300)
def load_config_text(output_dir: str):
    """Raw krkn-ai.yaml text — keeps the comments yaml.safe_load throws away."""
    config_path = os.path.join(output_dir, "krkn-ai.yaml")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                return f.read()
        except Exception as e:
            logging.error(f"Failed to read {config_path}: {e}")
    return ""


@st.cache_data(ttl=300)
def load_config_yaml(output_dir: str):
    try:
        return yaml.safe_load(load_config_text(output_dir)) or None
    except Exception as e:
        logging.error(f"Failed to parse {output_dir}/krkn-ai.yaml: {e}")
        return None


@st.cache_data(ttl=300)
def load_learned_weights(output_dir: str):
    """Weights the engine learned from this run, keyed by query. Empty when absent."""
    return read_learned_weights(os.path.join(output_dir, LEARNED_WEIGHTS_FILE))


def _catalog_matchers():
    """Regex per catalog entry, with $ns left open, to recognise a query in a config."""
    global _CATALOG_MATCHERS
    if _CATALOG_MATCHERS is None:
        matchers = []
        try:
            from krkn_ai.utils.catalog import get_base_catalog

            catalog = get_base_catalog()
        except Exception as e:  # catalog is optional for the dashboard
            logging.error(f"Could not load the fitness catalog: {e}")
            catalog = []

        for entry in catalog:
            pattern = re.escape(entry.query_template)
            pattern = pattern.replace(re.escape("$ns"), r"(?P<ns>[^\"]+)", 1).replace(
                re.escape("$ns"), r"(?P=ns)"
            )
            pattern = rf"^\(?{pattern}\)?(?:\s+or\s+vector\(0\))?$"
            try:
                matchers.append((re.compile(pattern), entry))
            except re.error as e:
                logging.error(f"Skipping catalog entry {entry.key}: {e}")
        _CATALOG_MATCHERS = matchers
    return _CATALOG_MATCHERS


def describe_query(query: str):
    """Return (name, category) for a query by matching it against the catalog."""
    for pattern, entry in _catalog_matchers():
        m = pattern.match(query or "")
        if not m:
            continue
        namespace = m.groupdict().get("ns")
        name = f"{entry.key}:{namespace}" if namespace else entry.key
        category = entry.category.value if entry.category else None
        return name, category
    return None, None


def _config_block(text: str, key: str) -> List[str]:
    """Lines under a top-level config key, comments included."""
    block: List[str] = []
    inside = False
    for line in (text or "").splitlines():
        if not line:
            if inside:
                block.append(line)
            continue
        bare = _COMMENT_MARKER_RE.sub("", line, count=1)
        top_level = bool(bare) and not bare[0].isspace()
        if top_level and bare.startswith(f"{key}:"):
            inside = True
            continue
        if inside:
            if top_level and _TOP_KEY_RE.match(bare):
                break
            block.append(line)
    return block


def _parse_fitness_comments(text: str):
    """Read discover's annotations: (names by query, queries it commented out)."""
    names, disabled = {}, []
    pending_name = pending_reason = None

    for line in _config_block(text, "fitness_function"):
        stripped = line.strip()
        if stripped.startswith("#"):
            body = stripped.lstrip("#").strip()
            inline = _INLINE_DISABLED_RE.match(body)
            if inline:
                disabled.append(
                    {
                        "name": inline.group("name"),
                        "reason": inline.group("reason"),
                        "query": _unquote(inline.group("query")),
                        "type": None,
                    }
                )
                pending_name = pending_reason = None
                continue

            query_match = _QUERY_RE.match(body)
            if query_match:
                disabled.append(
                    {
                        "name": pending_name,
                        "reason": pending_reason or "",
                        "query": _unquote(query_match.group("query")),
                        "type": None,
                    }
                )
                pending_name = pending_reason = None
                continue

            type_match = _TYPE_RE.match(body)
            if type_match and disabled:
                disabled[-1]["type"] = type_match.group("type")
                continue

            named = _NAME_RE.match(body)
            pending_name = named.group("name") if named else None
            pending_reason = named.group("reason") if named else None
            continue

        query_match = _QUERY_RE.match(stripped)
        if query_match and pending_name and not pending_reason:
            names[_unquote(query_match.group("query"))] = pending_name
        pending_name = pending_reason = None

    return names, disabled


@st.cache_data(ttl=300)
def load_fitness_items(output_dir: str):
    """Fitness queries in use plus the ones discover rejected, with their reason."""
    config = load_config_yaml(output_dir) or {}
    fitness_function = config.get("fitness_function") or {}
    names, disabled = _parse_fitness_comments(load_config_text(output_dir))

    items = []
    for item in fitness_function.get("items") or []:
        query = item.get("query", "")
        catalog_name, category = describe_query(query)
        items.append(
            {
                "name": names.get(query) or catalog_name or _short_query(query),
                "category": category,
                "query": query,
                "type": item.get("type", ""),
                "weight": float(item.get("weight", 1.0)),
                "id": item.get("id"),
                "enabled": True,
                "reason": "",
            }
        )

    for entry in disabled:
        catalog_name, category = describe_query(entry["query"])
        items.append(
            {
                "name": entry["name"] or catalog_name or _short_query(entry["query"]),
                "category": category,
                "query": entry["query"],
                "type": entry["type"] or "",
                "weight": 0.0,
                "id": None,
                "enabled": False,
                "reason": entry["reason"],
            }
        )

    return items


def slo_columns(columns):
    """All slo_* columns present, in id order."""
    return sorted(
        (c for c in columns if _SLO_RE.match(str(c))),
        key=lambda c: int(str(c).split("_")[1]),
    )


def map_slo_columns(items, columns):
    """Pair each enabled item with its slo_* column in all.csv."""
    enabled = [item for item in items if item["enabled"]]
    if not enabled:
        return {}

    if all(item.get("id") is not None for item in enabled):
        by_id = {f"slo_{item['id']}": item for item in enabled}
        if all(col in columns for col in by_id):
            return by_id
        return {}

    slo_cols = slo_columns(columns)
    if not slo_cols or len(slo_cols) != len(enabled):
        return {}
    return {col: item for col, item in zip(slo_cols, enabled)}


@st.cache_data(ttl=300)
def load_health_check_recos(output_dir: str):
    """Health-check applications discover commented out, with the reason it gave."""
    disabled, pending = [], None
    for line in _config_block(load_config_text(output_dir), "health_checks"):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        body = stripped.lstrip("#").strip()
        reason = _HC_REASON_RE.match(body)
        if reason:
            pending = reason.group("reason")
            continue
        name = _HC_NAME_RE.match(body)
        if name:
            disabled.append(
                {"name": _unquote(name.group("name")), "url": "", "reason": pending}
            )
            continue
        url = _HC_URL_RE.match(body)
        if url and disabled:
            disabled[-1]["url"] = _unquote(url.group("url"))
    return [d for d in disabled if d["reason"]]


@st.cache_data(ttl=300)
def _get_output_config(output_dir: str) -> OutputConfig:
    """Load the output filename config for a run, falling back to defaults."""
    raw = load_config_yaml(output_dir)
    try:
        return OutputConfig(**(raw or {}).get("output", {}))
    except Exception as e:
        logging.error(f"Failed to parse output config for {output_dir}: {e}")
        return OutputConfig()


@st.cache_data(ttl=300)
def load_detailed_scenarios_data(output_dir: str):
    output_config = _get_output_config(output_dir)
    yaml_glob = fmt_to_glob(output_config.result_name_fmt)
    base_name, _ext = os.path.splitext(yaml_glob)
    yaml_glob = f"{base_name}.yaml"
    yaml_pattern = os.path.join(output_dir, "yaml", "generation_*", yaml_glob)
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


@st.cache_data(ttl=300)
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


@st.cache_data(ttl=300)
def load_logs(output_dir: str):
    """
    Parse all scenario log files (matched using the run's configured
    log_name_fmt) and return a list of structured dicts, one per scenario,
    containing everything needed for the report card.
    """

    log_dir = os.path.join(output_dir, "logs")
    if not os.path.isdir(log_dir):
        return []

    output_config = _get_output_config(output_dir)
    log_glob = fmt_to_glob(output_config.log_name_fmt)
    log_id_regex = fmt_to_id_regex(output_config.log_name_fmt)

    # Matches: "2026-03-17 11:58:12,164 [INFO] message..."
    log_re = re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})(?:,\d+)?\s+\[(?P<level>[A-Z]+)\]\s+(?P<msg>.*)$"
    )
    # Duration line at the end: "container-scenarios ran for 3m12.701171021s"
    duration_re = re.compile(r"^(.+)\s+ran\s+for\s+([\dhms.]+)$")
    # ANSI stripping
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")

    results = []
    for log_file in sorted(glob.glob(os.path.join(log_dir, log_glob))):
        base = os.path.basename(log_file)
        m = log_id_regex.match(base)
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

        def get_distribution():
            dist_m = re.search(
                r"Detected distribution\s+([a-zA-Z0-9_-]+)", clean_raw, re.IGNORECASE
            )
            if dist_m:
                return dist_m.group(1).capitalize()
            return jval("distribution") or jval("distribution_type") or "—"

        # Top-level telemetry fields
        telemetry = {
            "run_uuid": jval("run_uuid") or "",
            "job_status": jval("job_status"),
            "cluster_version": jval("cluster_version") or "",
            "timestamp": jval("timestamp") or "",
            "total_node_count": jval("total_node_count") or 0,
            "network_plugins": jlist("network_plugins") or ["Unknown"],
            "distribution": get_distribution(),
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
                "distribution": telemetry.get("distribution", "Kubernetes"),
            }
        )

    return results
