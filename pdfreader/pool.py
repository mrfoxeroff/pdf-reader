"""GUI-side manager of the worker processes (see worker.py)."""
from __future__ import annotations

import itertools
import multiprocessing as mp
import os
import threading
from collections import OrderedDict, deque

from PySide6.QtCore import QObject, Signal

from .worker import worker_main


class _Worker:
    def __init__(self, ctx, name):
        self.conn, child = ctx.Pipe(duplex=True)
        self.proc = ctx.Process(target=worker_main, args=(child,), daemon=True, name=name)
        self.proc.start()
        child.close()
        self.busy = 0
        self.lock = threading.Lock()

    def send(self, msg):
        with self.lock:
            self.conn.send(msg)


class WorkerPool(QObject):
    """Dispatches render and text jobs to worker processes.

    Render requests are kept in a GUI-side queue and handed out newest-first
    only when a worker becomes idle, so outdated requests (pages scrolled past)
    are never rendered.
    """

    _received = Signal(object)

    MAX_IN_FLIGHT = 2

    def __init__(self, render_workers: int | None = None):
        super().__init__()
        ctx = mp.get_context("spawn")
        n = render_workers or max(1, min(3, (os.cpu_count() or 2) - 1))
        self._render = [_Worker(ctx, f"pdf-render-{i}") for i in range(n)]
        self._text = _Worker(ctx, "pdf-text")
        self._ids = itertools.count(1)
        self._jobs: dict[int, tuple] = {}            # job id -> (callback, worker)
        self._render_queue: OrderedDict = OrderedDict()  # key -> (msg_builder, callback)
        self._thumb_queue: OrderedDict = OrderedDict()
        self._text_queue: deque = deque()
        self._queued_keys: dict = {}                 # render key -> job id in flight
        self._closed = False
        self._received.connect(self._on_received)
        for w in self._render + [self._text]:
            threading.Thread(target=self._reader, args=(w,), daemon=True).start()

    # ----------------------------------------------------------- lifecycle
    def shutdown(self):
        self._closed = True
        for w in self._render + [self._text]:
            try:
                w.send(("quit",))
            except Exception:
                pass
        for w in self._render + [self._text]:
            w.proc.join(timeout=0.5)
            if w.proc.is_alive():
                w.proc.kill()

    def close_document(self, doc_id: int):
        for w in self._render + [self._text]:
            try:
                w.send(("close", doc_id))
            except Exception:
                pass

    # -------------------------------------------------------------- render
    def submit_render(self, key, build, callback, thumb=False):
        """Queue a render job. ``build()`` returns the message tail when sent."""
        if key in self._queued_keys:
            return
        q = self._thumb_queue if thumb else self._render_queue
        q[key] = (build, callback)
        q.move_to_end(key)
        self._dispatch()

    def is_queued(self, key) -> bool:
        return key in self._queued_keys or key in self._render_queue or key in self._thumb_queue

    def retain(self, owner, wanted: set):
        """Drop queued (not yet sent) tile jobs of ``owner`` not in ``wanted``."""
        for k in [k for k in self._render_queue if k[1] == owner and k not in wanted]:
            del self._render_queue[k]

    def forget_owner(self, owner):
        for q in (self._render_queue, self._thumb_queue):
            for k in [k for k in q if k[1] == owner]:
                del q[k]
        self._text_queue = deque(j for j in self._text_queue if j[0] != owner)

    # ---------------------------------------------------------------- text
    def submit_text(self, owner, build, callback):
        self._text_queue.append((owner, build, callback))
        self._dispatch_text()

    # ------------------------------------------------------------ internal
    def _dispatch(self):
        if self._closed:
            return
        for w in self._render:
            while w.busy < self.MAX_IN_FLIGHT:
                if self._render_queue:
                    key, (build, cb) = self._render_queue.popitem(last=True)
                elif self._thumb_queue:
                    key, (build, cb) = self._thumb_queue.popitem(last=False)
                else:
                    return
                msg = build()
                if msg is None:
                    continue
                job_id = next(self._ids)
                self._jobs[job_id] = (cb, w, key)
                self._queued_keys[key] = job_id
                w.busy += 1
                try:
                    w.send((msg[0], job_id) + tuple(msg[1:]))
                except Exception:
                    w.busy -= 1
                    self._jobs.pop(job_id, None)
                    self._queued_keys.pop(key, None)

    def _dispatch_text(self):
        w = self._text
        while not self._closed and w.busy < 1 and self._text_queue:
            owner, build, cb = self._text_queue.popleft()
            msg = build()
            if msg is None:
                continue
            job_id = next(self._ids)
            self._jobs[job_id] = (cb, w, None)
            w.busy += 1
            try:
                w.send((msg[0], job_id) + tuple(msg[1:]))
            except Exception:
                w.busy -= 1
                self._jobs.pop(job_id, None)

    def _reader(self, w: _Worker):
        while True:
            try:
                msg = w.conn.recv()
            except (EOFError, OSError):
                return
            self._received.emit(msg)

    def _on_received(self, msg):
        job_id = msg[1]
        entry = self._jobs.pop(job_id, None)
        if entry is None:
            return
        cb, w, key = entry
        w.busy -= 1
        if key is not None:
            self._queued_keys.pop(key, None)
        try:
            cb(msg)
        finally:
            if w is self._text:
                self._dispatch_text()
            else:
                self._dispatch()


_pool: WorkerPool | None = None


def pool() -> WorkerPool:
    global _pool
    if _pool is None:
        _pool = WorkerPool()
    return _pool


def shutdown_pool():
    global _pool
    if _pool is not None:
        _pool.shutdown()
        _pool = None
