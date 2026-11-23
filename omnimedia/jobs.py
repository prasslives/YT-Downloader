"""Shared job plumbing: progress reporting and cancellation."""

from __future__ import annotations

import threading
import time
from typing import Protocol


class Cancelled(Exception):
    """Raised when the user cancels a running job."""


class Reporter(Protocol):
    def log(self, message: str, level: str = "info") -> None: ...
    def progress(self, percent: float | None, status: str, detail: str = "") -> None: ...


class ConsoleReporter:
    """Reporter that prints to stdout (used for CLI / tests)."""

    def log(self, message: str, level: str = "info") -> None:
        print(f"[{level}] {message}")

    def progress(self, percent: float | None, status: str, detail: str = "") -> None:
        pct = "--" if percent is None else f"{percent:5.1f}%"
        print(f"  {pct} {status} {detail}")


class Throttle:
    """Lets at most one call through every `interval` seconds (forced calls always pass)."""

    def __init__(self, interval: float = 0.15):
        self.interval = interval
        self._last = 0.0
        self._lock = threading.Lock()

    def ready(self, force: bool = False) -> bool:
        with self._lock:
            now = time.monotonic()
            if force or now - self._last >= self.interval:
                self._last = now
                return True
            return False


def human_bytes(n: float | None) -> str:
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def unique_path(path: str) -> str:
    """Return `path`, or 'name (2).ext', 'name (3).ext'... if it already exists."""
    import os

    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{stem} ({i}){ext}"):
        i += 1
    return f"{stem} ({i}){ext}"
