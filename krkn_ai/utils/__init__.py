import shlex
import subprocess
import threading
from typing import Iterator, Optional

from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


def id_generator() -> Iterator[int]:
    i = 1
    while True:
        yield i
        i += 1


def run_shell(command, do_not_log=False, timeout: Optional[int] = None):
    """
    Run shell command and get logs and statuscode in output.

    Args:
        command: Shell command to execute
        do_not_log: If True, suppress debug logging of command output
        timeout: Maximum execution time in seconds. If None, no timeout is applied.
                 If the timeout expires, the process is terminated and return code -1 is returned.

    Returns:
        Tuple of (logs, returncode). On timeout, returncode is -1.
    """
    logs = ""
    command_list = shlex.split(command)
    # Let's show the command name being executed
    logger.debug("Running command: %s", command_list[0])

    process = subprocess.Popen(
        command_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    # Use a timer to enforce timeout since we're reading stdout line-by-line
    timed_out = threading.Event()

    def kill_on_timeout():
        timed_out.set()
        logger.error(
            "Command timed out after %d seconds, terminating: %s", timeout, command_list[0]
        )
        process.terminate()
        # Give process time to terminate gracefully, then force kill
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Process did not terminate gracefully, sending SIGKILL")
            process.kill()

    timer = None
    if timeout is not None:
        timer = threading.Timer(timeout, kill_on_timeout)
        timer.start()

    try:
        for line in process.stdout:
            if not do_not_log:
                logger.debug("%s", line.rstrip())
            logs += line
        process.wait()
    finally:
        if timer is not None:
            timer.cancel()

    if timed_out.is_set():
        logger.error("Command execution timed out")
        return logs, -1

    logger.debug("Run Status: %d", process.returncode)
    return logs, process.returncode
