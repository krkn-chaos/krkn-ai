import os
import json
import tempfile
from unittest.mock import patch

from krkn_ai.dashboard.app import (
    get_monitor_config,
    is_execution_running,
    get_run_status,
)
from krkn_ai.constants import (
    STATUS_STARTED,
    STATUS_COMPLETED,
    STATUS_FAILED,
)


def test_get_monitor_config():
    with patch("sys.argv", ["app.py", "--output-dir", "/custom/dir"]):
        config = get_monitor_config()
        assert config["output_dir"] == "/custom/dir"


def test_get_monitor_config_default():
    with patch("sys.argv", ["app.py"]):
        config = get_monitor_config()
        assert config["output_dir"] == "./"


def test_is_execution_running_no_file():
    assert is_execution_running("/non/existent/dir") is False


def test_is_execution_running_true():
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "results.json"), "w") as f:
            json.dump({"status": STATUS_STARTED}, f)

        assert is_execution_running(tmpdir) is True


def test_is_execution_running_false():
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "results.json"), "w") as f:
            json.dump({"status": STATUS_COMPLETED}, f)

        assert is_execution_running(tmpdir) is False


def test_get_run_status_no_file():
    assert get_run_status("/non/existent/dir") is None


def test_get_run_status_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "results.json"), "w") as f:
            json.dump({"status": STATUS_FAILED}, f)

        assert get_run_status(tmpdir) == STATUS_FAILED
