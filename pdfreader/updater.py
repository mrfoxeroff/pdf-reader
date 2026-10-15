"""Self-update from GitHub Releases.

The latest release of the repository is queried through the public GitHub
API. An update downloads the installer (or the portable exe), checks its
SHA-256 digest, then a hidden PowerShell helper waits for this process to
exit, runs the installer silently over the current installation and starts
the new version.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from .version import VERSION

REPO = "mrfoxeroff/pdf-reader"
# PDFREADER_UPDATE_API may point to another JSON (also file://) for testing
API_LATEST = os.environ.get("PDFREADER_UPDATE_API") or f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
USER_AGENT = f"PDFReader/{VERSION}"
NO_WINDOW = 0x08000000


@dataclass
class Asset:
    name: str
    url: str
    size: int
    sha256: str | None


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    page_url: str
    setup: Asset | None
    portable: Asset | None


def parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums[:4]) or (0,)


def current_version() -> str:
    # PDFREADER_FAKE_VERSION lets the update path be tested without a new release
    return os.environ.get("PDFREADER_FAKE_VERSION") or VERSION


def is_newer(release: Release) -> bool:
    return parse_version(release.version) > parse_version(current_version())


def install_kind() -> str:
    """'installed' (by the setup), 'portable' (single exe) or 'source'."""
    if not getattr(sys, "frozen", False):
        return "source"
    app_dir = os.path.dirname(sys.executable)
    if any(f.lower().startswith("unins") and f.lower().endswith(".exe") for f in os.listdir(app_dir)):
        return "installed"
    return "portable"


def fetch_latest(timeout: float = 15) -> Release:
    req = urllib.request.Request(API_LATEST, headers={
        "Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    setup = portable = None
    for a in data.get("assets", []):
        name = a.get("name", "")
        digest = a.get("digest") or ""
        asset = Asset(name, a.get("browser_download_url", ""), int(a.get("size", 0)),
                      digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None)
        low = name.lower()
        if low.startswith("pdfreader-setup") and low.endswith(".exe"):
            setup = asset
        elif low.startswith("pdfreader-portable") and low.endswith(".exe"):
            portable = asset
    tag = data.get("tag_name", "")
    return Release(version=tag.lstrip("vV"), tag=tag, notes=data.get("body") or "",
                   page_url=data.get("html_url") or RELEASES_PAGE, setup=setup, portable=portable)


def asset_for_this_install(release: Release) -> Asset | None:
    return release.portable if install_kind() == "portable" else release.setup


def download_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "PDFReaderUpdate")
    os.makedirs(d, exist_ok=True)
    return d


# ===================================================================== Qt API
class UpdateChecker(QObject):
    """Checks GitHub in a background thread."""

    found = Signal(object)     # Release (newer than the running version)
    upToDate = Signal(object)  # Release
    failed = Signal(str)

    def check(self):
        threading.Thread(target=self._run, daemon=True, name="update-check").start()

    def _run(self):
        try:
            rel = fetch_latest()
        except Exception as exc:
            self.failed.emit(_net_error(exc))
            return
        (self.found if is_newer(rel) else self.upToDate).emit(rel)


class Downloader(QObject):
    progress = Signal(int, int)   # bytes done, total
    finished = Signal(str)        # local path
    failed = Signal(str)

    def __init__(self, asset: Asset):
        super().__init__()
        self.asset = asset
        self._cancel = False

    def start(self):
        threading.Thread(target=self._run, daemon=True, name="update-download").start()

    def cancel(self):
        self._cancel = True

    def _run(self):
        a = self.asset
        path = os.path.join(download_dir(), a.name)
        part = path + ".part"
        try:
            req = urllib.request.Request(a.url, headers={"User-Agent": USER_AGENT})
            sha = hashlib.sha256()
            done = 0
            last_emit = 0.0
            with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or a.size or 0)
                while True:
                    if self._cancel:
                        raise _Cancelled()
                    chunk = r.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_emit > 0.05:
                        last_emit = now
                        self.progress.emit(done, total)
            self.progress.emit(done, total or done)
            if a.size and done != a.size:
                raise IOError("файл скачан не полностью")
            if a.sha256 and sha.hexdigest() != a.sha256:
                raise IOError("контрольная сумма не совпадает — файл повреждён")
            os.replace(part, path)
            self.finished.emit(path)
        except _Cancelled:
            _silent_remove(part)
        except Exception as exc:
            _silent_remove(part)
            self.failed.emit(_net_error(exc))


class _Cancelled(Exception):
    pass


def _silent_remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _net_error(exc) -> str:
    text = str(exc)
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
        return "На GitHub пока нет опубликованных версий."
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)) and "getaddrinfo" in text:
        return "Нет подключения к интернету."
    return text or exc.__class__.__name__


# ================================================================ applying
def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _run_hidden_powershell(script: str):
    """Start PowerShell with a hidden console so it outlives this process."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", encoded]
    new_group = 0x00000200          # CREATE_NEW_PROCESS_GROUP
    breakaway = 0x01000000          # CREATE_BREAKAWAY_FROM_JOB
    try:
        subprocess.Popen(args, creationflags=NO_WINDOW | new_group | breakaway, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:  # the job does not allow breakaway
        subprocess.Popen(args, creationflags=NO_WINDOW | new_group, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply_update(path: str) -> None:
    """Start the helper that installs ``path`` once this process has exited.

    The caller must quit the application right after this returns.
    """
    pid = os.getpid()
    kind = install_kind()
    exe = sys.executable
    if kind == "installed":
        app_dir = os.path.dirname(exe)
        pf = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]
        all_users = any(p and os.path.normcase(app_dir).startswith(os.path.normcase(p)) for p in pf)
        args = ("/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /RELAUNCH=1 "
                + ("/ALLUSERS " if all_users else "/CURRENTUSER ")
                + f'/DIR="{app_dir}"')
        script = (
            f"Wait-Process -Id {pid} -Timeout 60 -ErrorAction SilentlyContinue; "
            f"Start-Sleep -Milliseconds 300; "
            f"Start-Process -FilePath {_ps_quote(path)} -ArgumentList {_ps_quote(args)}"
        )
    elif kind == "portable":
        script = (
            f"Wait-Process -Id {pid} -Timeout 60 -ErrorAction SilentlyContinue; "
            f"$ok = $false; for ($i = 0; $i -lt 40 -and -not $ok; $i++) {{ "
            f"try {{ Copy-Item -LiteralPath {_ps_quote(path)} -Destination {_ps_quote(exe)} -Force "
            f"-ErrorAction Stop; $ok = $true }} catch {{ Start-Sleep -Milliseconds 250 }} }}; "
            f"Start-Process -FilePath {_ps_quote(exe)}"
        )
    else:
        raise RuntimeError("Программа запущена из исходников: обновите её через git pull.")
    _run_hidden_powershell(script)


def cleanup_downloads(keep_newer_than: str | None = None):
    """Remove old downloaded installers (called at start-up)."""
    d = os.path.join(tempfile.gettempdir(), "PDFReaderUpdate")
    if not os.path.isdir(d):
        return
    for f in os.listdir(d):
        p = os.path.join(d, f)
        try:
            if time.time() - os.path.getmtime(p) > 3600:
                os.remove(p)
        except OSError:
            pass
