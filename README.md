# Unified AI Gateway Pro

A bring-your-own-key (BYOK) gateway that multiplexes your own API keys from
multiple AI providers behind one OpenAI-compatible endpoint. You paste in
keys you already own; the gateway stores them encrypted, routes chat
requests across providers with automatic failover, and tracks usage and
estimated cost.

What this is not: the gateway never creates accounts, never signs up for
services, never solves CAPTCHAs, and never harvests keys. Experimental
automation from an earlier prototype lives isolated under
`legacy/quarantine/` and is not imported by the gateway.

## Quickstart

Prerequisites: Python 3.10+ and the bundled virtualenv.

```bash
cd Unified-AI-Gateway-Pro
cp .env.example .env          # then edit .env and set UAG_ADMIN_TOKEN
.venv/bin/python -m gateway.cli serve
```

The gateway listens on `http://127.0.0.1:8008` by default. Open
`http://127.0.0.1:8008/dashboard` for the web dashboard.

Add your first key (the secret is typed hidden, never echoed):

```bash
export UAG_ADMIN_TOKEN=your-token
.venv/bin/python -m gateway.cli keys add --provider kilo --label main
```

Send a chat request:

```bash
curl http://127.0.0.1:8008/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "kilo-auto/free",
       "messages": [{"role": "user", "content": "hello"}]}'
```

If `UAG_REQUIRE_PUBLIC_AUTH=true`, add `-H "Authorization: Bearer $UAG_ADMIN_TOKEN"`.

## Configuration

`config/gateway.json` holds providers and models; every setting can be
overridden with a `UAG_*` environment variable (see `.env.example`).
Key files and SQLite databases live under `data/` (configurable with
`UAG_DATA_DIR`).

## CLI reference

Run from the repo root: `.venv/bin/python -m gateway.cli <command>`.
Global flags: `--config PATH`, `--host H`, `--port P`, `--token T`
(token defaults to `UAG_ADMIN_TOKEN`). Exit codes: 0 ok, 1 failure,
2 usage error.

| Command | Description |
|---|---|
| `serve [--host --port]` | Run the gateway server (foreground) |
| `status` | Gateway status: uptime, providers, key and model counts |
| `providers` | Providers with health, key counts, model counts |
| `models` | Models with priority and fallback chains |
| `keys list [--provider P]` | Stored keys (always masked, never raw) |
| `keys add --provider P --label L` | Add a key; secret read hidden via getpass |
| `keys enable --id ID` | Enable a key |
| `keys disable --id ID` | Disable a key |
| `keys remove --id ID` | Delete a key |
| `health` | Per-provider health snapshot |
| `usage [--days N]` | Requests, tokens, estimated cost, latency |
| `config show` | Sanitized config (token blanked); live view with `--token` |
| `logs [--lines N]` | Tail `data/gateway.log` via the admin API |
| `test` | Run the pytest suite |

## API reference

Public (OpenAI-compatible):

- `GET /healthz` - liveness, no auth required
- `GET /v1/models` - enabled models
- `POST /v1/chat/completions` - chat; set `"stream": true` for SSE

Admin (`/admin/*`, bearer token required):

- `GET /admin/status` - status overview
- `GET /admin/providers` - providers plus health snapshot
- `GET /admin/models`, `POST /admin/models`, `PATCH /admin/models/{id}` - model registry
- `GET /admin/keys`, `POST /admin/keys`, `PATCH /admin/keys/{id}`, `DELETE /admin/keys/{id}` - key management (masked)
- `GET /admin/usage?days=N` - usage and cost summary
- `GET /admin/requests?limit=N&status=` - recent request log
- `GET /admin/health` - per-provider health checks
- `GET /admin/logs?lines=N` - tail the log file
- `GET /admin/config` - sanitized config

The web dashboard is served at `/` and `/dashboard`.

## Routing behavior

- Models resolve to a primary provider plus enabled fallback models.
- 429/5xx: retried with backoff, then the next key, then the next model.
- 401/403: the failing key is rotated out (cooled down), request continues.
- 400/404: fail fast, no retries.
- Circuit breaker: a provider that keeps failing is skipped for a cooldown.
- Every attempt is bounded; the router never loops forever.

## Watchdog

`gateway/watchdog.py` supervises the gateway process: it polls
`/healthz` and `/admin/health`, and after 3 consecutive failures restarts
the gateway with exponential backoff (30s, 60s, 120s, capped at 600s).
At most 5 restarts per rolling hour; after that it logs CRITICAL and keeps
polling without restarting, so a broken service is never restarted in a
tight loop. See `WATCHDOG.md`.

```bash
.venv/bin/python -m gateway.watchdog --interval 30
```

## Testing

```bash
.venv/bin/python -m pytest tests/ -q
# or
.venv/bin/python -m gateway.cli test
```

Tests cover the keystore (masking, round-trip, selection, failure
accounting), the router (fallback, fast failure, key rotation, circuit
breaker, attempt bounds), the HTTP API (auth, masking, mocked chat), usage
arithmetic, config loading, and security (permissions, token auth).

## Security

- API keys are encrypted at rest with Fernet; the master key file is
  created with mode `0600`.
- Keys are masked in every API response, log line, and CLI output.
  Raw secrets are never returned or printed.
- Admin endpoints require a bearer token; without `UAG_ADMIN_TOKEN`
  they reject everything.
- Request bodies are size-limited; oversized payloads get 413.
- Auth failures use constant-time comparison.

## Quarantine note

`legacy/quarantine/` holds the old experimental key-harvesting automation.
It is not part of the gateway, is not imported by any gateway module,
and must stay that way. Do not wire it back in.

## Repository layout

- `gateway/` - the gateway package (app, router, providers, keystore,
  registry, usage, health, config, logging, CLI, watchdog, dashboard)
- `config/gateway.json` - providers and models
- `data/` - SQLite databases, master key, logs (git-ignored)
- `tests/` - pytest suite
- `legacy/quarantine/` - isolated legacy experiments, not imported
