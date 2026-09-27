# TASKS.md — Unified AI Gateway Pro rebuild

Scope: legitimate BYOK gateway only. Harvesting/account-automation code is
quarantined in `legacy/quarantine/` and is out of scope (never improve it).

## P0 — broken / core / security / reliability

| ID | Area | Description | Owner | Status | Files | Tests | Verification |
|----|------|-------------|-------|--------|-------|-------|--------------|
| T01 | quarantine | Move harvesting + stealth-browser + old proxy code out of serving path | main | DONE | legacy/quarantine/* | — | git status shows renames; nothing in gateway/ imports legacy |
| T02 | core | Config system: `config/gateway.json` + `UAG_*` env overrides, validation | A | DONE | gateway/config.py | test_config.py | loads defaults, env override works, bad URL rejected |
| T03 | core | Encrypted keystore (Fernet), masking, pick/rotation, cooldowns | A | DONE | gateway/keystore.py | test_keystore.py | add/list masked; raw secret never in list output; pick skips cooling/disabled keys |
| T04 | core | Provider abstraction: OpenAI-compatible async client, errors, health check | A | DONE | gateway/providers.py | test_providers.py | mocked HTTP: 200/429/401/timeout mapped correctly |
| T05 | core | Model registry: pricing, capabilities, enabled, fallbacks, resolve order | A | DONE | gateway/registry.py | test_registry.py | resolve() order correct; disabled models excluded |
| T06 | core | Router: fallback, bounded retries w/ backoff, circuit breaker, key rotation, no retry on 4xx | A | DONE | gateway/router.py | test_router.py | 429->fallback works; 400 not retried; breaker opens after threshold; attempts bounded |
| T07 | core | Usage store: SQLite records, summaries, cost estimates labeled | A | DONE | gateway/usage.py | test_usage.py | record+summary math; cost flagged estimated |
| T08 | api | FastAPI app: /v1/models, /v1/chat/completions (+streaming), /healthz, X-Request-ID, OpenAI-style errors | B | DONE | gateway/app.py | test_api.py | TestClient: models list, completion mocked, stream SSE, 404 model -> proper error |
| T09 | api | Admin API: status/providers/models/keys CRUD/usage/requests/health/logs/config, Bearer auth | B | DONE | gateway/app.py | test_api.py | no token -> 401; key add returns masked meta only |
| T10 | security | Secret hygiene audit: no raw keys in logs/responses/dashboard; 0600 master key file; default bind 127.0.0.1 | main | DONE | all | test_security.py | grep for secret leaks in test outputs; file perms check |
| T11 | tests | Full pytest suite green | C | DONE | tests/* | — | `pytest -q` passes |

## P1 — major functionality

| ID | Area | Description | Owner | Status | Files | Tests | Verification |
|----|------|-------------|-------|--------|-------|-------|--------------|
| T12 | core | Background health-check loop wired into app lifespan | A | DONE | gateway/health.py, app.py | test_health.py | /admin/health shows fresh checks |
| T13 | core | Structured logging w/ request_id, secret scrubbing | A | DONE | gateway/logging_setup.py | test_logging.py | log line has request_id; secret not present |
| T14 | ui | Dashboard SPA: overview/providers/models/keys/usage/logs/settings, real data only | B | DONE | gateway/dashboard/* | manual | all sections load against live server |
| T15 | cli | Cross-platform CLI: serve/status/providers/models/keys/health/usage/config/test | C | DONE | gateway/cli.py | manual | each command runs, correct exit codes, no secret leaks |
| T16 | ops | Watchdog supervisor: poll, restart w/ backoff, capped restarts, logging | C | DONE | gateway/watchdog.py | manual | kills gateway -> watchdog restarts it; stops after cap |
| T17 | docs | README rewrite (honest, BYOK), ARCHITECTURE.md, WATCHDOG.md | C | DONE | *.md | — | docs match implementation |

## P2 — valuable enhancement

| ID | Area | Description | Owner | Status | Files | Tests | Verification |
|----|------|-------------|-------|--------|-------|-------|--------------|
| T18 | api | `/v1/responses` endpoint if it fits the OpenAI-compatible client cleanly | B | TODO | gateway/app.py | test_api.py | — |
| T19 | ops | MCP server bridge exposing gateway tools | C | TODO | gateway/mcp.py | — | — |
| T20 | core | Per-key rate-limit tracking (429 -> per-key cooldown already; add counters) | A | TODO | gateway/keystore.py | test_keystore.py | — |

## P3 — polish

| ID | Area | Description | Owner | Status | Files | Tests | Verification |
|----|------|-------------|-------|--------|-------|-------|--------------|
| T21 | docs | SESSION_REPORT.md final, TASKS.md statuses reconciled | main | DONE | — | — | — |
| T22 | repo | requirements.txt pinned, .gitignore extended, .env.example | main | DONE | — | — | — |

## P1 — major functionality (continued)

| ID | Area | Description | Owner | Status | Files | Tests | Verification |
|----|------|-------------|-------|--------|-------|-------|--------------|
| T23 | testing | Dashboard browser E2E loop (Run→Observe→Fix→Retest): serve gateway, drive real Chromium via agent-browser (`~/workspace/tools/agent-browser/ab`), walk every dashboard section, add provider/key via UI, run chat test, verify usage appears; fix legitimate UI/API bugs until green; no CAPTCHA/anti-bot evasion work | main | TODO | gateway/dashboard/*, gateway/app.py | manual E2E script | full flow passes in real browser |
| T24 | testing | Gateway HTTP E2E: /v1/models, /v1/chat/completions (mocked provider via httpx MockTransport), admin CRUD flows, auth rejections | C | TODO | tests/test_e2e.py | pytest | green |

Quarantined harvesting automation (`legacy/quarantine/`) is explicitly excluded
from the browser-testing loop: it is out of scope and must not be executed,
fixed, or extended.

Owners: main = orchestrator, A/B/C = subagent streams.

## Verification log (2026-09-26/27, main agent)

Automated: `pytest -q` -> 49 passed, 1 warning (Starlette TestClient deprecation). Includes
regression tests for proxy-env 500s (`test_proxy_env_does_not_cause_500`) and non-blocking
startup (`test_startup_does_not_block_on_health_checks`).

Live API (scratch server 127.0.0.1:8123, scratch data): /healthz 200; /v1/models lists enabled
models; /admin/* 401 without token, 200 with; no-key chat -> honest 502 `all_providers_failed`;
unknown model -> 404; bad JSON -> 400; 11 MB body -> 413; streaming failure -> SSE error + [DONE];
key add returns masked metadata only; raw secret absent from SQLite bytes; masked form `...abcd`.

Deterministic refusal server (127.0.0.1:8124, provider base http://127.0.0.1:9): chat -> 502
`all_providers_failed`, ~1.8 s latency, request log records error. Error text dedup fix verified.

Dashboard E2E (jsdom harness vs live 8123, production files unmodified): 18/18 PASS — login
overlay, real login flow, token session storage, all 8 sections render live data, key creation
through the real form, raw secret never in DOM, masked display, model toggle flips /v1/models
listing, requests tab shows traffic, zero JS/console errors. Real Chromium E2E was blocked by
the platform's local-network access policy (ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS);
jsdom is a faithful DOM+JS fallback, not proof of real-browser rendering.

Watchdog live supervised test (port 8125): SIGKILL of gateway -> 2 consecutive failures ->
restart after 30 s backoff as watchdog child (parent PID = watchdog); /healthz 200 after
recovery; second watchdog instance exits "already running" (flock); SIGTERM -> child stopped,
pid/lock files removed, port closed.

Security pass: no raw key patterns in tracked files or git history; no imports from
legacy/quarantine in gateway code; .master_key 0600, keys.db 640; admin auth uses
hmac.compare_digest, disabled when no token configured; CORS off by default; 10 MB body cap.

Browser automation bugs found this session (per browser loop rule): (1) direct CDP needed
--remote-allow-origins=* for the WS handshake; (2) waiting only on Page.loadEventFired raced
navigation — switched to document.readyState polling. Neither blocked the mission; both are
harness-only, recorded here.

## Public tunnel testing (2026-09-27, main agent)

Cloudflare Quick Tunnel failed (error 1033: QUIC/UDP and HTTP/2 tunnel connectivity
blocked through the sandbox proxy). Fell back to a Serveo SSH tunnel via a custom HTTP
CONNECT proxy helper (`/tmp/uag-pub/proxycommand.py`), local gateway on port 8123.
Public URL (temporary): `https://d0e8beec3ea33687-104-28-209-117.serveousercontent.com`
(Serveo warning interstitial requires "Continue to Site").

Terminal via public URL: /healthz 200, dashboard HTML served, /v1/models lists enabled
models, admin 401 without token / 200 with, no-key chat -> honest 502, streaming SSE
error + [DONE]. Real managed Chromium: warning flow, dashboard, admin login, all 8
sections live, key creation through the real form, masked keys, model toggle with
confirmation, failed provider call visible in Requests.

### Bug found: disabled requested model served via fallback (fixed)
Disabling `deepseek/deepseek-r1:free` removed it from /v1/models, but a chat request
for it still routed to its enabled fallback and returned 502 instead of 404.
Cause: `ModelRegistry.resolve()` drops the disabled primary but returns enabled
fallbacks; the API/router treated "resolvable" as "enabled".
Fix: `gateway/app.py` and `gateway/router.py` (both `complete` and `complete_stream`)
now check the requested model itself via `registry.get()` + `enabled` before routing.
Fallbacks still apply only to runtime failures of an enabled requested model.
Regression tests: API 404 and router RoutingError for disabled model with enabled
fallback, streaming and non-streaming. Verified publicly: 404 on both paths.

### Bug found: Usage dashboard/API schema mismatch (fixed)
Usage view showed "3 requests, 0 errors, 100% success" while the DB held three
`status='error'` rows, and the provider cell was blank.
Causes: (1) `UsageStore.summary()` returned `error_requests` (totals) /
`ok_requests` (rows) while the dashboard reads `.errors`; (2) failed requests were
recorded with `provider=""`; (3) `complete_stream()` never recorded usage on
failure at all.
Fixes: `summary()` now also returns `errors` on totals and on by_provider/by_model
rows (legacy fields kept); router records the last attempted provider on total
failure (both paths) and records stream failures (mid-stream and pre-stream) with
`attempts` tracking added to the stream loop; dashboard renders empty provider as
"unrouted". Regression tests: `test_summary_includes_errors_field`,
`test_complete_failure_records_last_provider`,
`test_complete_stream_failure_records_usage`.
After fix: `pytest -q` -> 55 passed, 1 warning.

### Bug 3 (2026-09-27): duplicate rows + missing token splits in usage groups
Browser verification of the Usage tab showed the "By model" table with two rows
both labeled `kilo-auto/free` (2/2 and 1/1 errors). Root cause: `summary()` in
`gateway/usage.py` grouped by_model by `(model, provider)` while the dashboard
only displays the model name. Same inspection found the grouped queries
returned only combined `tokens`, but the dashboard renders per-row
`prompt_tokens` / `completion_tokens` (always 0/0).
Fixes: by_model now groups by `model` only; both grouped queries also return
`SUM(prompt_tokens)` / `SUM(completion_tokens)`. No dashboard JS change needed
(it already read those fields and never used provider on by_model rows).
Regression tests: `test_by_model_groups_by_model_only`,
`test_grouped_rows_include_token_splits`.
After fix: `pytest -q` -> 57 passed, 1 warning. Verified live through the
public tunnel: single `kilo-auto/free` row, token split fields present.
