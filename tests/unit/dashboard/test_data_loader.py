import json
import streamlit as st
import pytest
import pandas as pd
import yaml
from unittest.mock import patch, mock_open

from krkn_ai.dashboard.data_loader import (
    load_results_csv,
    load_config_yaml,
    load_detailed_scenarios_data,
    load_health_check_csv,
    load_logs,
)


@pytest.fixture(autouse=True)
def clear_cache():
    st.cache_data.clear()


def test_load_results_csv_not_exists():
    with patch("os.path.exists", return_value=False):
        exists, df = load_results_csv("/tmp")
        assert exists is False
        assert df is None


def test_load_results_csv_exists_empty():
    with (
        patch("os.path.exists", return_value=True),
        patch("pandas.read_csv", return_value=pd.DataFrame()),
    ):
        exists, df = load_results_csv("/tmp")
        assert exists is True
        assert df is None


def test_load_results_csv_exists_with_data():
    mock_df = pd.DataFrame({"col1": [1, 2]})
    with (
        patch("os.path.exists", return_value=True),
        patch("pandas.read_csv", return_value=mock_df),
    ):
        exists, df = load_results_csv("/tmp")
        assert exists is True
        pd.testing.assert_frame_equal(df, mock_df)


def test_load_results_csv_exception():
    with (
        patch("os.path.exists", return_value=True),
        patch("pandas.read_csv", side_effect=Exception("Read error")),
    ):
        exists, df = load_results_csv("/tmp")
        assert exists is True
        assert df is None


def test_load_config_yaml_not_exists():
    with patch("os.path.exists", return_value=False):
        config = load_config_yaml("/tmp")
        assert config is None


def test_load_config_yaml_exists():
    yaml_content = "key: value\n"
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=yaml_content)),
    ):
        config = load_config_yaml("/tmp")
        assert config == {"key": "value"}


def test_load_config_yaml_exception():
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", side_effect=Exception("Open error")),
    ):
        config = load_config_yaml("/tmp")
        assert config is None


def test_load_health_check_csv_not_exists():
    with patch("os.path.exists", return_value=False):
        exists, df = load_health_check_csv("/tmp")
        assert exists is False
        assert df is None


def test_load_health_check_csv_exists_with_data():
    mock_df = pd.DataFrame({"health": ["ok", "fail"]})
    with (
        patch("os.path.exists", return_value=True),
        patch("pandas.read_csv", return_value=mock_df),
    ):
        exists, df = load_health_check_csv("/tmp")
        assert exists is True
        pd.testing.assert_frame_equal(df, mock_df)


def test_load_health_check_csv_exception():
    with (
        patch("os.path.exists", return_value=True),
        patch("pandas.read_csv", side_effect=Exception("Read error")),
    ):
        exists, df = load_health_check_csv("/tmp")
        assert exists is True
        assert df is None


def test_load_detailed_scenarios_data_no_files():
    with patch("glob.glob", return_value=[]):
        df = load_detailed_scenarios_data("/tmp")
        assert df.empty


def test_load_detailed_scenarios_data_valid_yaml(tmp_path):
    yaml_content = """
scenario_id: "scen_1"
start_time: "2026-05-19T10:00:00Z"
health_check_results:
  url1:
    - timestamp: "2026-05-19T10:00:05Z"
      name: "svc1"
      response_time: 0.5
      status_code: 200
      success: true
      error: null
"""
    gen_dir = tmp_path / "yaml" / "generation_0"
    gen_dir.mkdir(parents=True)
    (gen_dir / "scenario_1.yaml").write_text(yaml_content)

    df = load_detailed_scenarios_data(str(tmp_path))

    assert len(df) == 1
    row = df.iloc[0]
    assert row["scenario_id"] == "scen_1"
    assert row["service"] == "svc1"
    assert bool(row["success"]) is True
    assert row["error"] == "None"
    assert row["seconds_into_scenario"] == 5.0


def test_load_detailed_scenarios_data_exception():
    with (
        patch("glob.glob", return_value=["/tmp/scen1.yaml"]),
        patch("builtins.open", side_effect=Exception("Parse error")),
    ):
        df = load_detailed_scenarios_data("/tmp")
        assert df.empty


def test_load_logs_no_dir():
    with patch("os.path.isdir", return_value=False):
        logs = load_logs("/tmp")
        assert logs == []


def test_load_logs_valid_log():
    log_content = """
Environment Value
FOO BAR

2026-03-17 11:58:12,164 [INFO] some message
"run_uuid" : "1234"
"distribution" : "OpenShift"
"kubernetes_objects_count": {"pods": 1}
"scenarios": [ {"scenario_type": "pod-kill", "exit_status": 0} ]
"node_summary_infos": [ {"architecture": "amd64", "os_version": "linux"} ]
"parameters": { "scenarios": [ {"action": "delete", "namespace": "default"} ] }
"recovered": ["pod1"]

container-scenarios ran for 3m12s
"""
    with (
        patch("os.path.isdir", return_value=True),
        patch("glob.glob", return_value=["/tmp/scenario_1.log"]),
        patch("builtins.open", mock_open(read_data=log_content)),
    ):
        logs = load_logs("/tmp")
        assert len(logs) == 1
        log = logs[0]
        assert log["scenario_id"] == 1
        assert log["run_uuid"] == 1234
        assert log["distribution"] == "OpenShift"
        assert log["scenario_type"] == "pod-kill"
        assert log["duration"] == "3m 12s"
        assert log["env_vars"] == {"FOO": "BAR"}
        assert log["affected_recovered"] == 1
        assert len(log["timeline"]) == 1


def test_load_logs_counts_affected_pods_not_arrays():
    """Recovered/unrecovered counts are pods, summed across scenarios, VMIs excluded"""

    def pod(name, recovery_time=None):
        return {
            "pod_name": name,
            "namespace": "shop",
            "total_recovery_time": recovery_time,
            "pod_readiness_time": None,
            "pod_rescheduling_time": None,
        }

    def vmi(name):
        return {"vmi_name": name, "namespace": "shop", "total_recovery_time": None}

    telemetry = {
        "scenarios": [
            {
                "scenario_type": "pod_disruption_scenarios",
                "affected_pods": {
                    "recovered": [
                        pod("cart-a", 4.2),
                        pod("cart-b", 3.9),
                        pod("cart-c", 4.0),
                    ],
                    "unrecovered": [pod("web-a"), pod("web-b")],
                },
                "affected_vmis": {
                    "recovered": [vmi("vm-a"), vmi("vm-b")],
                    "unrecovered": [],
                },
            },
            {
                "scenario_type": "pod_disruption_scenarios",
                "affected_pods": {
                    "recovered": [pod("cart-d", 5.0)],
                    "unrecovered": [],
                },
                "affected_vmis": {"recovered": [], "unrecovered": []},
            },
        ]
    }
    log_content = json.dumps(telemetry, indent=2)

    with (
        patch("os.path.isdir", return_value=True),
        patch("glob.glob", return_value=["/tmp/scenario_1.log"]),
        patch("builtins.open", mock_open(read_data=log_content)),
    ):
        log = load_logs("/tmp")[0]

    assert log["affected_recovered"] == 4
    assert log["affected_unrecovered"] == 2


def test_load_logs_exception():
    with (
        patch("os.path.isdir", return_value=True),
        patch("glob.glob", return_value=["/tmp/scenario_1.log"]),
        patch("builtins.open", side_effect=Exception("Read error")),
    ):
        logs = load_logs("/tmp")
        assert logs == []


def test_load_detailed_scenarios_data_reads_json_results(tmp_path):
    """A run saved with -f json writes json/generation_*/*.json; its health
    check rows must reach the dashboard like a yaml run's do."""
    result = {
        "scenario_id": 7,
        "start_time": "2026-11-03T10:00:00",
        "health_check_results": {
            "http://cart": [
                {
                    "name": "cart",
                    "timestamp": "2026-11-03T10:00:05",
                    "response_time": 0.2,
                    "status_code": 200,
                    "success": True,
                    "error": None,
                }
            ]
        },
    }
    gen_dir = tmp_path / "json" / "generation_0"
    gen_dir.mkdir(parents=True)
    (gen_dir / "scenario_7.json").write_text(json.dumps(result))

    with patch("krkn_ai.dashboard.data_loader.load_config_yaml", return_value=None):
        df = load_detailed_scenarios_data(str(tmp_path))

    assert list(df["scenario_id"]) == ["7"]
    assert list(df["seconds_into_scenario"]) == [5.0]


@pytest.mark.parametrize("fmt, dump", [("json", json.dumps), ("yaml", yaml.safe_dump)])
def test_load_detailed_scenarios_data_uses_configured_result_fmt(tmp_path, fmt, dump):
    """Results in either format are found using the configured filename."""
    result = {
        "scenario_id": 3,
        "start_time": "2026-11-03T10:00:00",
        "health_check_results": {
            "http://cart": [{"name": "cart", "timestamp": "2026-11-03T10:00:01"}]
        },
    }
    gen_dir = tmp_path / fmt / "generation_0"
    gen_dir.mkdir(parents=True)
    (gen_dir / f"gen_0_x_3.{fmt}").write_text(dump(result))

    with patch(
        "krkn_ai.dashboard.data_loader.load_config_yaml",
        return_value={"output": {"result_name_fmt": "gen_%g_%c_%s.yaml"}},
    ):
        df = load_detailed_scenarios_data(str(tmp_path))

    assert list(df["scenario_id"]) == ["3"]


def test_load_detailed_scenarios_data_json_keeps_small_numbers_numeric(tmp_path):
    """json.dumps writes a tiny float as 1e-06, which YAML reads as a string;
    the heatmaps aggregate response_time, so it must stay a number."""
    result = {
        "scenario_id": 1,
        "start_time": "2026-11-03T10:00:00",
        "health_check_results": {
            "http://cart": [
                {
                    "name": "cart",
                    "timestamp": "2026-11-03T10:00:01",
                    "response_time": 0.000001,
                }
            ]
        },
    }
    gen_dir = tmp_path / "json" / "generation_0"
    gen_dir.mkdir(parents=True)
    (gen_dir / "scenario_1.json").write_text(json.dumps(result))

    with patch("krkn_ai.dashboard.data_loader.load_config_yaml", return_value=None):
        df = load_detailed_scenarios_data(str(tmp_path))

    assert pd.api.types.is_numeric_dtype(df["response_time"])
    assert df["response_time"].iloc[0] == 0.000001


def test_load_logs_uses_configured_log_fmt_for_scenario_id():
    log_content = """
2026-03-17 11:58:12,164 [INFO] some message

container-scenarios ran for 3m12s
"""
    with (
        patch("os.path.isdir", return_value=True),
        patch(
            "krkn_ai.dashboard.data_loader.load_config_yaml",
            return_value={"output": {"log_name_fmt": "run_%g_%s.log"}},
        ),
        patch("glob.glob", return_value=["/tmp/logs/run_0_7.log"]),
        patch("builtins.open", mock_open(read_data=log_content)),
    ):
        logs = load_logs("/tmp")
        assert len(logs) == 1
        assert logs[0]["scenario_id"] == 7


def test_load_logs_falls_back_to_default_fmt_when_no_config():
    log_content = """
2026-03-17 11:58:12,164 [INFO] some message

container-scenarios ran for 3m12s
"""
    with (
        patch("os.path.isdir", return_value=True),
        patch("krkn_ai.dashboard.data_loader.load_config_yaml", return_value=None),
        patch("glob.glob", return_value=["/tmp/logs/scenario_9.log"]),
        patch("builtins.open", mock_open(read_data=log_content)),
    ):
        logs = load_logs("/tmp")
        assert len(logs) == 1
        assert logs[0]["scenario_id"] == 9


@pytest.mark.parametrize(
    ("raw_duration", "expected"),
    [
        ("500ms", "0s"),
        ("1.5ms", "0s"),
        ("1s500ms", "1s"),
        ("1m2.5s", "1m 2s"),
        ("0s", "0s"),
    ],
)
def test_load_logs_does_not_interpret_milliseconds_as_minutes(
    tmp_path, raw_duration, expected
):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "scenario_1.log").write_text(
        f"container-scenarios ran for {raw_duration}\n", encoding="utf-8"
    )
    logs = load_logs(str(tmp_path))
    assert len(logs) == 1
    assert logs[0]["duration"] == expected
