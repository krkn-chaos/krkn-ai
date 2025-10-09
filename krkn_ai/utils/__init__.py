import shlex
import subprocess
from typing import Iterator

from krkn_ai.utils.logger import get_module_logger

logger = get_module_logger(__name__)


def id_generator() -> Iterator[int]:
    i = 1
    while True:
        yield i
        i += 1


def run_shell(command, do_not_log=False):
    '''
    Run shell command and get logs and statuscode in output.
    '''
    logger.debug("Running command: %s", command)
    logs = ""
    command = shlex.split(command)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    for line in process.stdout:
        if not do_not_log:
            logger.debug("%s", line.rstrip())
        logs += line
    process.wait()
    logger.debug("Run Status: %d", process.returncode)
    return logs, process.returncode
