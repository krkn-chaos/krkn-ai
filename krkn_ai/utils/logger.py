# logger_setup.py
import logging
import os
from typing import Optional

_LOGGER_INITIALIZED = False
_LOG_DIR: Optional[str] = None

def init_logger(output_dir: Optional[str] = None, verbose: bool = False):
    """Initialize global logger configuration once."""

    global _LOGGER_INITIALIZED, _LOG_DIR
    if _LOGGER_INITIALIZED:
        return

    _LOG_DIR = output_dir
    log_level = logging.DEBUG if verbose else logging.INFO

    # Create root-safe parent logger name
    parent_name = "krkn-ai"
    parent = logging.getLogger(parent_name)

    # Set root logger to critical level to avoid logging to console
    logging.getLogger().setLevel(logging.CRITICAL)

    # Avoid re-adding handlers if already configured
    if parent.handlers:
        _LOGGER_INITIALIZED = True
        return

    # Configure parent logger: handlers live here, children will propagate to it
    parent.setLevel(logging.DEBUG)         # accept all levels; handler controls output
    parent.propagate = False               # don't let messages go to root

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    parent.addHandler(console)

    # Optional file handler
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, "run.log")
        fh = logging.FileHandler(file_path)
        fh.setLevel(logging.DEBUG)   # capture everything in file
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        parent.addHandler(fh)

    _LOGGER_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger under the 'krkn-ai' namespace so it inherits parent's handlers.
    Example: get_logger(__name__) -> logger name "krkn-ai.mypackage.module"
    """
    # Ensure calling code doesn't accidentally use the root logger
    base = "krkn-ai"
    if name and not name.startswith(base):
        fullname = f"{base}.{name}"
    else:
        fullname = name or base
    return logging.getLogger(fullname)


def get_log_dir() -> Optional[str]:
    return _LOG_DIR
