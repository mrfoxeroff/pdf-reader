"""GUI side of Word <-> PDF conversion (runs convert.run_job in a process)."""
from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QProgressDialog

from . import convert


class ConversionRunner(QObject):
    """Runs one conversion in a child process; can be cancelled."""

    finished = Signal(str, str)   # dst, backend
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, kind: str, src: str, dst: str, backend: str):
        super().__init__()
        self.kind, self.src, self.dst, self.backend = kind, src, dst, backend
        self._word_pids: list[int] = []
        self._done = False
        self._proc = None

    def start(self):
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe(duplex=False)
        self._proc = ctx.Process(target=convert.run_job,
                                 args=(child, self.kind, self.src, self.dst, self.backend),
                                 daemon=True, name="pdf-convert")
        self._proc.start()
        child.close()
        threading.Thread(target=self._read, args=(parent,), daemon=True).start()

    def _read(self, conn):
        result = None
        while True:
            try:
                msg = conn.recv()
            except (EOFError, OSError):
                break
            if msg[0] == "pid":
                self._word_pids.append(msg[1])
            elif msg[0] == "progress":
                self.progress.emit(msg[1], msg[2])
            else:
                result = msg
                break
        self._done = True
        if result is None:
            self.failed.emit("Процесс преобразования неожиданно завершился.")
        elif result[0] == "done":
            self.finished.emit(self.dst, result[1])
        else:
            self.failed.emit(result[1])

    def cancel(self):
        if self._done:
            return
        if self._proc is not None and self._proc.is_alive():
            self._proc.kill()
        for pid in self._word_pids:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           creationflags=convert.NO_WINDOW,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            if os.path.exists(self.dst):
                os.remove(self.dst)
        except OSError:
            pass


def run_with_progress(parent, kind: str, src: str, dst: str, on_done, on_error):
    """Show a modal progress dialog while converting ``src`` to ``dst``."""
    try:
        backend = convert.pick_backend(kind, src)
    except convert.ConversionError as exc:
        on_error(str(exc))
        return None
    name = os.path.basename(src)
    what = "в PDF" if kind == "to_pdf" else "в Word (DOCX)"
    dlg = QProgressDialog(f"Преобразование «{name}» {what}\n"
                          f"({convert.describe_backend(backend)})…", "Отмена", 0, 0, parent)
    dlg.setWindowTitle("Преобразование")
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setMinimumWidth(420)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    runner = ConversionRunner(kind, src, dst, backend)
    state = {"cancelled": False}

    def finished(path, used):
        dlg.close()
        QApplication.restoreOverrideCursor()
        on_done(path, used)

    def failed(msg):
        dlg.close()
        QApplication.restoreOverrideCursor()
        if not state["cancelled"]:
            on_error(msg)

    def progress(i, n):
        dlg.setRange(0, n)
        dlg.setValue(i)
        dlg.setLabelText(f"Преобразование «{name}» {what}: страница {i + 1} из {n}")

    def cancelled():
        state["cancelled"] = True
        runner.cancel()
        QApplication.restoreOverrideCursor()

    runner.finished.connect(finished)
    runner.failed.connect(failed)
    runner.progress.connect(progress)
    dlg.canceled.connect(cancelled)
    QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
    runner.start()
    dlg.show()
    # keep the runner alive as long as the dialog exists
    dlg._runner = runner
    QTimer.singleShot(0, dlg.raise_)
    return runner
