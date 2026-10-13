"""Atomic file replacement helpers for runner artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_bytes(path: str | Path, content: bytes) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".krkn-ai-tmp-", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def atomic_write_text(path: str | Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))
