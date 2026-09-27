#!/usr/bin/env python3
"""Watchdog supervisor for the Unified AI Gateway Pro.

Polls the gateway's /healthz and /admin/health endpoints. After
``--fail-threshold`` consecutive failures it restarts the gateway via
``python -m gateway.cli serve`` with exponential backoff (30s, 60s, 120s,
... capped at 600s). At most ``--max-restarts`` restarts per rolling hour;
once the cap is hit it logs CRITICAL and keeps polling without restarting,
so it never endlessly restarts a failing service.

Single instance is enforced with a lock file. PID state lives in
``data/watchdog.pid`` and logs go to ``data/watchdog.log``. The lock and
PID files are always cleaned up on exit.

Usage:
    python -m gateway.watchdog [--interval 30] [--fail-threshold 3]
                               [--config config/gateway.json]
"""
from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import subprocess
import sys
import time
from collections import deque

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gateway.config import load_settings  # noqa: E402

_BACKOFF_START_S = 30
_BACKOFF_CAP_S = 600


class Watchdog:
    def __init__(self, args):
        self.args = args
        self.settings = load_settings(config_path=args.config)
        self.host = args.host or self.settings.host
        self.port = args.port or self.settings.port
        self.token = (
            args.token
            or os.environ.get("UAG_ADMIN_TOKEN", "").strip()
            or self.settings.admin_token
            or ""
        )
        self.interval = args.interval
        self.threshold = args.fail_threshold
        self.max_restarts = args.max_restarts
        self.window_s = args.window_s

        self.data_dir = self.settings.data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.lock_path = os.path.join(self.data_dir, "watchdog.lock")
        self.pid_path = os.path.join(self.data_dir, "watchdog.pid")
        self.child_log = os.path.join(self.data_dir, "gateway-stdout.log")

        self.log = self._setup_logging()

        self.child: subprocess.Popen | None = None
        self.consec_failures = 0
        self.sick_warned = False
        self.backoff_idx = 0
        self.restart_times: deque[float] = deque()
        self.restart_disabled = False
        self._stop = False
        self._lock_fh = None

    # ---------------- setup ---------------- #
    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("watchdog")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh = logging.FileHandler(os.path.join(self.data_dir, "watchdog.log"),
                                 encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        return logger

    def acquire_lock(self) -> bool:
        self._lock_fh = open(self.lock_path, "w")
        try:
            fcntl.flock(self._lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self._lock_fh.write(str(os.getpid()))
        self._lock_fh.flush()
        return True

    # ---------------- health ---------------- #
    def probe(self) -> str:
        """Return 'ok', 'sick' (up but unhealthy), or 'down'."""
        import httpx

        base = f"http://{self.host}:{self.port}"
        # trust_env=False: never send local health checks through a proxy
        try:
            r = httpx.get(f"{base}/healthz", timeout=5.0, trust_env=False)
        except Exception:
            return "down"
        if r.status_code != 200:
            return "sick"
        if self.token:
            try:
                r = httpx.get(
                    f"{base}/admin/health", timeout=5.0, trust_env=False,
                    headers={"Authorization": f"Bearer {self.token}"})
            except Exception:
                return "down"
            return "ok" if r.status_code == 200 else "sick"
        return "ok"

    # ---------------- child management ---------------- #
    def _start_child(self) -> None:
        cmd = [sys.executable, "-m", "gateway.cli", "serve",
               "--host", self.host, "--port", str(self.port),
               "--config", self.args.config]
        out = open(self.child_log, "a", encoding="utf-8")
        self.child = subprocess.Popen(
            cmd, cwd=REPO_ROOT,
            stdout=out, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
        self.log.info("started gateway (pid=%s)", self.child.pid)

    def _stop_child(self) -> None:
        child, self.child = self.child, None
        if child is None or child.poll() is not None:
            return
        self.log.info("stopping gateway (pid=%s)", child.pid)
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.log.warning("gateway did not stop, killing (pid=%s)", child.pid)
            child.kill()

    def _prune_restarts(self) -> None:
        now = time.time()
        while self.restart_times and now - self.restart_times[0] > self.window_s:
            self.restart_times.popleft()

    def _restart_allowed(self) -> bool:
        self._prune_restarts()
        if len(self.restart_times) >= self.max_restarts:
            if not self.restart_disabled:
                self.restart_disabled = True
                self.log.critical(
                    "restart cap reached (%d restarts in the last %ds): "
                    "will keep polling but will NOT restart again",
                    self.max_restarts, self.window_s)
            return False
        return True

    def _backoff(self) -> float:
        return min(_BACKOFF_START_S * (2 ** self.backoff_idx), _BACKOFF_CAP_S)

    def handle_failure(self, state: str) -> None:
        self.consec_failures += 1
        self.log.warning("gateway %s (%d/%d consecutive failures)",
                         state, self.consec_failures, self.threshold)
        if self.consec_failures < self.threshold:
            return
        self.consec_failures = 0

        if state == "sick" and self.child is None:
            # someone else's gateway is up but unhealthy; never kill it
            if not self.sick_warned:
                self.sick_warned = True
                self.log.warning(
                    "gateway is up but unhealthy and is not managed by this "
                    "watchdog; not restarting (manual intervention needed)")
            return
        self.sick_warned = False

        if not self._restart_allowed():
            return
        delay = self._backoff()
        self.log.warning("restarting gateway in %.0fs (restart %d of max %d "
                         "per %ds window)", delay,
                         len(self.restart_times) + 1, self.max_restarts,
                         self.window_s)
        self._sleep(delay)
        if self._stop:
            return
        self._stop_child()
        self._start_child()
        self.restart_times.append(time.time())
        self.backoff_idx += 1

    # ---------------- main loop ---------------- #
    def _sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while not self._stop and time.time() < end:
            time.sleep(min(0.5, end - time.time()))

    def _on_signal(self, signum, _frame) -> None:
        self.log.info("received signal %s, shutting down", signum)
        self._stop = True

    def run(self) -> int:
        if not self.acquire_lock():
            print("another watchdog instance is already running; exiting",
                  file=sys.stderr)
            return 1
        with open(self.pid_path, "w") as f:
            f.write(str(os.getpid()))
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

        self.log.info(
            "watchdog started (pid=%s): polling http://%s:%s every %ss, "
            "restart after %d failures, max %d restarts per %ds",
            os.getpid(), self.host, self.port, self.interval,
            self.threshold, self.max_restarts, self.window_s)
        if not self.token:
            self.log.warning("no admin token configured: only /healthz will "
                             "be probed, not /admin/health")
        try:
            while not self._stop:
                if self.child is not None and self.child.poll() is not None:
                    self.log.warning("managed gateway exited (rc=%s)",
                                     self.child.returncode)
                    self.child = None
                    self.handle_failure("down")
                else:
                    state = self.probe()
                    if state == "ok":
                        if self.consec_failures:
                            self.log.info("gateway healthy again")
                        self.consec_failures = 0
                        self.backoff_idx = 0
                    else:
                        self.handle_failure(state)
                self._sleep(self.interval)
        finally:
            self._stop_child()
            for path in (self.pid_path, self.lock_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            if self._lock_fh is not None:
                try:
                    fcntl.flock(self._lock_fh, fcntl.LOCK_UN)
                    self._lock_fh.close()
                except OSError:
                    pass
            self.log.info("watchdog stopped")
        return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Unified AI Gateway Pro watchdog")
    p.add_argument("--interval", type=float, default=30.0,
                   help="seconds between health polls (default: 30)")
    p.add_argument("--fail-threshold", type=int, default=3,
                   help="consecutive failures before a restart (default: 3)")
    p.add_argument("--max-restarts", type=int, default=5,
                   help="max restarts per rolling window (default: 5)")
    p.add_argument("--window-s", type=float, default=3600.0,
                   help="rolling window for the restart cap, seconds (default: 3600)")
    p.add_argument("--config", default=None,
                   help="config file path (default: config/gateway.json)")
    p.add_argument("--host", default=None, help="gateway host override")
    p.add_argument("--port", type=int, default=None, help="gateway port override")
    p.add_argument("--token", default=None,
                   help="admin token (default: UAG_ADMIN_TOKEN or config)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.config is None:
        args.config = os.environ.get(
            "UAG_CONFIG_PATH",
            os.path.join(REPO_ROOT, "config", "gateway.json"))
    return Watchdog(args).run()


if __name__ == "__main__":
    sys.exit(main())
