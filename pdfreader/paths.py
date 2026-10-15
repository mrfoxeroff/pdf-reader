"""Filesystem locations used by the application."""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

_temp: str | None = None


def resource_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def temp_dir() -> str:
    """Per-session temporary directory, removed on exit."""
    global _temp
    if _temp is None:
        _temp = tempfile.mkdtemp(prefix="pdfreader_")
        atexit.register(lambda: shutil.rmtree(_temp, ignore_errors=True))
    return _temp
