import shlex
import subprocess
import threading
from typing import Iterator

from krkn_ai.models.custom_errors import ShellCommandTimeoutError
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


def id_generator() -> Iterator[int]:
    i = 0
    while True:
        yield i
        i += 1


def run_shell(command, do_not_log=False, timeout=None):
    """
    Run shell command and get logs and statuscode in output.

    Raises:
        ShellCommandTimeoutError: If the command does not complete within
            the specified timeout (in seconds).
    """
    command = shlex.split(command)
    logger.debug("Running command: %s", command[0])

    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    output_lines = []

    def _read_output():
        for line in process.stdout:
            if not do_not_log:
                logger.debug("%s", line.rstrip())
            output_lines.append(line)

    reader = threading.Thread(target=_read_output, daemon=True)
    reader.start()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            # Wait for process to terminate gracefully
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Forcefully terminate
            process.kill()
            process.wait()
        reader.join(timeout=5)
        raise ShellCommandTimeoutError(
            f"Command '{command[0]}' timed out after {timeout} seconds"
        )

    reader.join(timeout=5)

    if not reader.is_alive() and process.stdout:
        process.stdout.close()

    logs = "".join(output_lines)

    logger.debug("Run Status: %d", process.returncode)

    return logs, process.returncode
