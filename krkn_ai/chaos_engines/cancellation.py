import signal
import threading
from contextlib import contextmanager


CANCELLATION_EVENT = threading.Event()
CANCELLATION_LOCK = threading.RLock()


class CancellationRequested(Exception):
    """Raised when cooperative cancellation prevents starting more work."""


def request_cancellation(signum=None, frame=None) -> None:
    with CANCELLATION_LOCK:
        CANCELLATION_EVENT.set()


def cancellation_requested() -> bool:
    return CANCELLATION_EVENT.is_set()


def reset_cancellation() -> None:
    with CANCELLATION_LOCK:
        CANCELLATION_EVENT.clear()


@contextmanager
def cancellation_commit_guard():
    """Serialize finalization against asynchronous cancellation requests."""
    with CANCELLATION_LOCK:
        yield CANCELLATION_EVENT.is_set()


@contextmanager
def handle_cancellation_signals():
    """Translate TERM/INT into cooperative cancellation and restore handlers."""
    reset_cancellation()
    previous = {
        signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        for signum in previous:
            signal.signal(signum, request_cancellation)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        reset_cancellation()
