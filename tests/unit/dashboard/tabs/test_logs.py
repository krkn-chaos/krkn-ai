from krkn_ai.dashboard.tabs.logs import (
    render_logs,
)

# Since render_logs writes directly to Streamlit, we will mock the Streamlit components
# to ensure the function works when passed different inputs.

from unittest.mock import patch


@patch("krkn_ai.dashboard.tabs.logs.st.warning")
@patch("krkn_ai.dashboard.tabs.logs.st.header")
def test_render_logs_empty(mock_header, mock_warning):
    render_logs([])
    mock_warning.assert_called_with("No log files found in the `logs/` directory.")


@patch("krkn_ai.dashboard.tabs.logs.st.info")
@patch("krkn_ai.dashboard.tabs.logs.st.code")
@patch(
    "krkn_ai.dashboard.tabs.logs.st.selectbox", return_value="Scenario 1 – scenario_one"
)
@patch("krkn_ai.dashboard.tabs.logs.st.header")
def test_render_logs_valid(mock_header, mock_selectbox, mock_code, mock_info):
    mock_logs = [{"scenario_id": "1", "raw_text": "log text", "job_status": True}]
    mock_scen_id_to_name = {"1": "scenario_one"}

    render_logs(mock_logs, mock_scen_id_to_name)

    mock_selectbox.assert_called_once()
    mock_code.assert_called_once_with("log text", language="log")
