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
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                assert process.stdout is not None  # guaranteed by PIPE
                assert process.stderr is not None  # guaranteed by PIPE
                # Check quickly if the process failed to start
                try:
                    retcode = process.wait(timeout=2)
                    # Process exited immediately — something went wrong
                    stdout = process.stdout.read().decode(errors="replace")
                    stderr = process.stderr.read().decode(errors="replace")
                    output = (stderr or stdout).strip()
                    logger.warning(
                        "Dashboard process exited immediately (code %d): %s",
                        retcode,
                        output,
                    )
                    return None
                except subprocess.TimeoutExpired:
                    # Still running after 2s — detach pipes so they don't block
                    process.stdout.close()
                    process.stderr.close()
                    logger.info(f"Dashboard running at http://localhost:{port}")
                    return process
            else:
                subprocess.run(cmd, check=True)
        except KeyboardInterrupt:
            logger.info("Monitoring dashboard stopped.")
        except Exception as e:
            logger.error(f"Failed to start monitoring dashboard: {e}")
            return None
