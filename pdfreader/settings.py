"""Persistent user settings (stored in the Windows registry via QSettings)."""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QSettings, QStandardPaths

MAX_RECENT = 15
MAX_POSITIONS = 300


class Settings:
    def __init__(self):
        self.q = QSettings("PDFReader", "PDFReader")

    # -------------------------------------------------------------- generic
    def get(self, key, default=None):
        v = self.q.value(key, default)
        if isinstance(default, bool) and not isinstance(v, bool):
            return str(v).lower() in ("1", "true", "yes")
        return v

    def set(self, key, value):
        self.q.setValue(key, value)

    def _json(self, key, default):
        raw = self.q.value(key, "")
        if not raw:
            return default
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return default

    def _set_json(self, key, value):
        self.q.setValue(key, json.dumps(value, ensure_ascii=False))

    # --------------------------------------------------------------- recent
    def recent_files(self) -> list[str]:
        return [p for p in self._json("recent", []) if isinstance(p, str)]

    def add_recent(self, path: str):
        path = os.path.abspath(path)
        items = [p for p in self.recent_files() if os.path.normcase(p) != os.path.normcase(path)]
        items.insert(0, path)
        self._set_json("recent", items[:MAX_RECENT])

    def remove_recent(self, path: str):
        self._set_json("recent", [p for p in self.recent_files() if p != path])

    def clear_recent(self):
        self._set_json("recent", [])

    # ------------------------------------------------------------ positions
    def position(self, path: str) -> dict | None:
        return self._json("positions", {}).get(os.path.normcase(os.path.abspath(path)))

    def save_position(self, path: str, state: dict):
        pos = self._json("positions", {})
        key = os.path.normcase(os.path.abspath(path))
        pos.pop(key, None)
        pos[key] = state
        if len(pos) > MAX_POSITIONS:
            for k in list(pos)[: len(pos) - MAX_POSITIONS]:
                del pos[k]
        self._set_json("positions", pos)

    # ----------------------------------------------------------------- misc
    def last_dir(self) -> str:
        d = self.q.value("last_dir", "")
        if d and os.path.isdir(d):
            return d
        return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)

    def set_last_dir(self, path: str):
        self.q.setValue("last_dir", os.path.dirname(os.path.abspath(path)))
