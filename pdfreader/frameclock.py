"""A frame clock synchronised with the display refresh (vsync).

Qt's animation timer ticks at a fixed ~60 Hz, which looks juddery on 120/144/
240 Hz monitors. On Windows ``DwmFlush`` blocks until the desktop compositor
presents the next frame, so a helper thread calling it in a loop yields one
tick per monitor refresh. Ticks are coalesced: a new one is only sent after
the GUI thread has handled the previous one.
"""
from __future__ import annotations

import sys
import threading
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

try:
    import ctypes

    _dwm_flush = ctypes.windll.dwmapi.DwmFlush if sys.platform == "win32" else None
except (AttributeError, OSError):
    _dwm_flush = None


def refresh_rate() -> float:
    screen = QGuiApplication.primaryScreen()
    rate = screen.refreshRate() if screen else 60.0
    return rate if 20 <= rate <= 1000 else 60.0


class FrameClock(QObject):
    tick = Signal(float)  # time.perf_counter() of the frame

    def __init__(self):
        super().__init__()
        self._users = 0
        self._cond = threading.Condition()
        self._pending = False
        self._period = 1.0 / refresh_rate()
        self._thread = threading.Thread(target=self._run, daemon=True, name="frame-clock")
        self._thread.start()
        self.tick.connect(self._delivered)

    def acquire(self):
        """Start ticking (reference counted)."""
        with self._cond:
            self._users += 1
            if self._users == 1:
                self._period = 1.0 / refresh_rate()
            self._cond.notify()

    def release(self):
        with self._cond:
            self._users = max(0, self._users - 1)

    def _delivered(self, _t):
        self._pending = False

    def _wait_frame(self, last: float) -> float:
        if _dwm_flush is not None:
            t0 = time.perf_counter()
            ok = _dwm_flush() == 0
            now = time.perf_counter()
            # DwmFlush may return at once (e.g. nothing to compose); never
            # tick faster than the monitor refresh.
            if ok and now - last >= self._period * 0.6:
                return now
            if ok and now - t0 > 0.001:
                return now
        delay = last + self._period - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        return time.perf_counter()

    def _run(self):
        last = time.perf_counter()
        while True:
            with self._cond:
                while self._users == 0:
                    self._cond.wait()
            last = self._wait_frame(last)
            if not self._pending:
                self._pending = True
                try:
                    self.tick.emit(last)
                except RuntimeError:  # application is shutting down
                    return


_clock: FrameClock | None = None


def clock() -> FrameClock:
    global _clock
    if _clock is None:
        _clock = FrameClock()
    return _clock
