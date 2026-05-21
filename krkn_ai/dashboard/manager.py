import os
import sys
import subprocess
from krkn_ai.utils.logger import get_logger


class DashboardManager:
    @staticmethod
    def start(output_dir: str, port: int, background: bool = True):
        logger = get_logger(__name__)
        dashboard_dir = os.path.dirname(__file__)
        actual_output = os.path.abspath(output_dir if output_dir else "./")

        cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            os.path.join(dashboard_dir, "app.py"),
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--",
            "--output-dir",
            actual_output,
        ]

        try:
            if background:
                log_file_path = os.path.join(actual_output, "dashboard.log")
                log_file = open(log_file_path, "a")

                try:
                    process = subprocess.Popen(
                        cmd,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                    )
                finally:
                    # Parent can safely close its file descriptor
                    log_file.close()

                # Check quickly if the process failed to start
                try:
                    retcode = process.wait(timeout=2)
                    # Process exited immediately — something went wrong
                    with open(log_file_path, "r", errors="replace") as f:
                        output = f.read().strip()
                    logger.warning(
                        "Dashboard process exited immediately (code %d): %s",
                        retcode,
                        output,
                    )
                    return None
                except subprocess.TimeoutExpired:
                    # Still running after 2s
                    logger.info(f"Dashboard running at http://localhost:{port}")
                    return process
            else:
                subprocess.run(cmd, check=True)
        except KeyboardInterrupt:
            logger.info("Monitoring dashboard stopped.")
        except Exception as e:
            logger.error(f"Failed to start monitoring dashboard: {e}")
            return None
