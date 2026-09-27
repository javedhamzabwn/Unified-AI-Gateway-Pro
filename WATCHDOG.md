# Watchdog

The watchdog (`gateway/watchdog.py`) keeps the gateway process alive. It is
a small supervisor loop, not part of the request path.

## What it does

Every `--interval` seconds (default 30) it probes:

1. `GET /healthz` - is the process up?
2. `GET /admin/health` - are the providers healthy? (only when an admin
   token is available via `--token`, `UAG_ADMIN_TOKEN`, or the config)

Each probe returns one of three states:

- `ok` - everything fine
- `sick` - the HTTP server answers but reports unhealthy
- `down` - connection refused or timed out

After `--fail-threshold` consecutive failures (default 3) the watchdog
restarts the gateway by running:

```bash
python -m gateway.cli serve --host <host> --port <port> --config <config>
```

using the repo's own Python interpreter, with stdout/stderr appended to
`data/gateway-stdout.log`.

## Safety rules

- **Exponential backoff.** Restarts wait 30s, then 60s, 120s, 240s, and so
  on, capped at 600s. A flapping service does not spin.
- **Restart cap.** At most `--max-restarts` restarts (default 5) per rolling
  `--window-s` window (default 3600s). Once the cap is hit the watchdog
  logs CRITICAL and keeps polling but never restarts again in that window.
- **Not-my-child rule.** If the gateway is `sick` but was not started by
  this watchdog (for example you run your own instance), the watchdog
  logs a warning and does not kill or replace it.
- **Single instance.** A lock file (`data/watchdog.lock`) guarantees only
  one watchdog runs per data directory. A second start exits with an
  error message.
- **Clean shutdown.** SIGTERM/SIGINT stops the managed gateway child,
  removes `data/watchdog.pid` and the lock file, and exits.

## State and logs

- PID: `data/watchdog.pid`
- Log: `data/watchdog.log` (also echoed to stdout)
- Child process output: `data/gateway-stdout.log`

## Usage

```bash
# from the repo root
.venv/bin/python -m gateway.watchdog --interval 30
.venv/bin/python -m gateway.watchdog --interval 15 --fail-threshold 5 \
    --max-restarts 3 --config /path/to/gateway.json
```

Run it in the background with your process manager of choice (systemd,
tmux, nohup). It runs in the foreground by design so a supervisor can
watch the watcher.

## Failure modes

| Symptom | What the watchdog does |
|---|---|
| Gateway process crashed | Detects exit, counts it as failure, restarts after threshold |
| Gateway hung (no HTTP response) | Probes time out, counts as failure, restarts after threshold |
| Provider API down but gateway up | `sick` state; restarts only if it manages the child |
| Gateway repeatedly crashing | Backoff grows, cap stops restarts, CRITICAL is logged |
| Another watchdog already running | New instance exits immediately |
