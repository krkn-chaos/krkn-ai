import streamlit as st
import pytest
import pandas as pd
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


def test_load_detailed_scenarios_data_valid_yaml():
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
    with (
        patch("glob.glob", return_value=["/tmp/scen1.yaml"]),
        patch("builtins.open", mock_open(read_data=yaml_content)),
    ):
        df = load_detailed_scenarios_data("/tmp")
        assert not df.empty
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


def test_load_logs_exception():
    with (
        patch("os.path.isdir", return_value=True),
        patch("glob.glob", return_value=["/tmp/scenario_1.log"]),
        patch("builtins.open", side_effect=Exception("Read error")),
    ):
        logs = load_logs("/tmp")
        assert logs == []
