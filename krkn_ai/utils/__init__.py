import logging
import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
from typing import Iterator

from krkn_ai.models.custom_errors import ShellCommandTimeoutError
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


def id_generator() -> Iterator[int]:
    i = 0
    while True:
        yield i
        i += 1


def _terminate_process_group(process, grace_period=5):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait()
        return

    deadline = time.monotonic() + grace_period
    while time.monotonic() < deadline:
        process.poll()
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    process.wait()


def run_shell(
    command, do_not_log=False, timeout=None, cancellation_event=None, cwd=None
):
    """
    Run shell command and get logs and statuscode in output.

    Raises:
        ShellCommandTimeoutError: If the command does not complete within
            the specified timeout (in seconds).
    """
    command = shlex.split(command)
    logger.debug("Running command: %s", command[0])

    if cancellation_event is not None and cancellation_event.is_set():
        return "", -signal.SIGTERM

    if not shutil.which(command[0]):
        level = logging.DEBUG if do_not_log else logging.ERROR
        logger.log(level, "Command not found: '%s'", command[0])
        return "", 127

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=cancellation_event is not None,
            cwd=cwd,
        )
    except OSError as e:
        level = logging.DEBUG if do_not_log else logging.ERROR
        logger.log(level, "Failed to execute '%s': %s", command[0], e)
        return "", 127

    output_lines = []

    def _read_output():
        for line in process.stdout:
            if not do_not_log:
                logger.debug("%s", line.rstrip())
            output_lines.append(line)

    reader = threading.Thread(target=_read_output, daemon=True)
    reader.start()
    cancellation_handled = False

    try:
        if cancellation_event is None:
            process.wait(timeout=timeout)
        else:
            deadline = None if timeout is None else time.monotonic() + timeout
            while process.poll() is None:
                wait_timeout = 0.1
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    wait_timeout = min(wait_timeout, remaining)
                if cancellation_event.wait(wait_timeout):
                    _terminate_process_group(process)
                    cancellation_handled = True
                    break
    except subprocess.TimeoutExpired:
        if cancellation_event is not None:
            _terminate_process_group(process)
        else:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        reader.join(timeout=5)
        raise ShellCommandTimeoutError(
            f"Command '{command[0]}' timed out after {timeout} seconds"
        )

    if cancellation_event is None:
        reader.join(timeout=5)
    else:
        reader_deadline = time.monotonic() + 5
        while reader.is_alive() and time.monotonic() < reader_deadline:
            reader.join(timeout=min(0.1, max(0, reader_deadline - time.monotonic())))
            if cancellation_event.is_set() and not cancellation_handled:
                _terminate_process_group(process)
                cancellation_handled = True
                break
        if cancellation_event.is_set():
            if not cancellation_handled:
                _terminate_process_group(process)
                cancellation_handled = True
            reader.join(timeout=5)

    if process.stdout:
        process.stdout.close()

    logs = "".join(output_lines)

    logger.debug("Run Status: %d", process.returncode)

    return logs, process.returncode
