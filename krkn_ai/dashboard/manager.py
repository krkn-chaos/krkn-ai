import os
import sys
import atexit
import subprocess
from typing import Optional
from krkn_ai.utils.logger import get_logger


class DashboardManager:
    def __init__(self, output_dir: str, port: int):
        self._output_dir = os.path.abspath(output_dir if output_dir else "./")
        self._port = port
        self._process: Optional[subprocess.Popen] = None
        self._logger = get_logger(__name__)

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> bool:
        """Launch Streamlit in background. Returns True if server started."""
        dashboard_dir = os.path.dirname(__file__)

        cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            os.path.join(dashboard_dir, "app.py"),
            "--server.port",
            str(self._port),
            "--server.headless",
            "true",
            "--",
            "--output-dir",
            self._output_dir,
        ]

        log_file_path = os.path.join(self._output_dir, "dashboard.log")

        try:
            log_file = open(log_file_path, "a")
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
            finally:
                log_file.close()

            # Check quickly if the process failed to start
            try:
                retcode = self._process.wait(timeout=2)
                with open(log_file_path, "r", errors="replace") as f:
                    output = f.read().strip()
                self._logger.warning(
                    "Dashboard process exited immediately (code %d): %s",
                    retcode,
                    output,
                )
                self._process = None
                return False
            except subprocess.TimeoutExpired:
                self._logger.info(
                    "Dashboard running at http://localhost:%s", self._port
                )
                atexit.register(self.stop)
                return True

        except Exception as e:
            self._logger.error("Failed to start monitoring dashboard: %s", e)
            self._process = None
            return False

    def stop(self):
        """Terminate the server if running. Idempotent."""
        if self._process is None or self._process.poll() is not None:
            return

        self._logger.info("Stopping dashboard server on port %s...", self._port)
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=5)
        self._logger.info("Dashboard server stopped.")

    def wait(self):
        """Block until the server process exits."""
        if self._process is not None:
            self._process.wait()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False
