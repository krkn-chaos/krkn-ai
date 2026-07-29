import subprocess
from unittest.mock import patch, Mock, mock_open
from krkn_ai.dashboard.manager import DashboardManager

MODULE = "krkn_ai.dashboard.manager"


def test_start_success():
    with (
        patch(f"{MODULE}.subprocess.Popen") as mock_popen,
        patch("builtins.open", mock_open()),
        patch(f"{MODULE}.atexit.register") as mock_atexit,
    ):
        mock_process = Mock()
        mock_process.wait.side_effect = subprocess.TimeoutExpired(cmd="cmd", timeout=2)
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        dm = DashboardManager("/tmp", 8080)
        result = dm.start()

        assert result is True
        assert dm.is_running
        mock_popen.assert_called_once()
        mock_atexit.assert_called_once_with(dm.stop)


def test_start_immediate_exit():
    with (
        patch(f"{MODULE}.subprocess.Popen") as mock_popen,
        patch("builtins.open", mock_open(read_data="error msg")),
    ):
        mock_process = Mock()
        mock_process.wait.return_value = 1
        mock_process.poll.return_value = 1
        mock_popen.return_value = mock_process

        dm = DashboardManager("/tmp", 8080)
        result = dm.start()

        assert result is False
        assert not dm.is_running
        mock_popen.assert_called_once()


def test_start_exception():
    with patch("builtins.open", side_effect=Exception("disk full")):
        dm = DashboardManager("/tmp", 8080)
        result = dm.start()

        assert result is False
        assert not dm.is_running


def test_stop_terminates_running_process():
    mock_process = Mock()
    mock_process.poll.return_value = None
    mock_process.wait.return_value = None

    dm = DashboardManager("/tmp", 8080)
    dm._process = mock_process

    dm.stop()

    mock_process.terminate.assert_called_once()


def test_stop_noop_when_already_exited():
    mock_process = Mock()
    mock_process.poll.return_value = 0

    dm = DashboardManager("/tmp", 8080)
    dm._process = mock_process

    dm.stop()

    mock_process.terminate.assert_not_called()


def test_stop_noop_when_no_process():
    dm = DashboardManager("/tmp", 8080)
    dm.stop()


def test_stop_kills_on_timeout():
    mock_process = Mock()
    mock_process.poll.return_value = None
    mock_process.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="cmd", timeout=5),
        None,
    ]

    dm = DashboardManager("/tmp", 8080)
    dm._process = mock_process

    dm.stop()

    mock_process.terminate.assert_called_once()
    mock_process.kill.assert_called_once()


def test_context_manager_starts_and_stops():
    with (
        patch(f"{MODULE}.subprocess.Popen") as mock_popen,
        patch("builtins.open", mock_open()),
        patch(f"{MODULE}.atexit.register"),
    ):
        mock_process = Mock()
        mock_process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="cmd", timeout=2),
            None,
        ]
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        with DashboardManager("/tmp", 8080) as dm:
            assert dm.is_running

        mock_process.terminate.assert_called_once()


def test_context_manager_stops_on_exception():
    with (
        patch(f"{MODULE}.subprocess.Popen") as mock_popen,
        patch("builtins.open", mock_open()),
        patch(f"{MODULE}.atexit.register"),
    ):
        mock_process = Mock()
        mock_process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="cmd", timeout=2),
            None,
        ]
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        try:
            with DashboardManager("/tmp", 8080):
                raise RuntimeError("simulated crash")
        except RuntimeError:
            pass

        mock_process.terminate.assert_called_once()
