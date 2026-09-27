# Unified AI Gateway Pro — Architecture

BYOK (bring-your-own-key) multi-provider AI gateway. Every API key in the
system is supplied by its owner via the admin API/CLI and stored encrypted.
There is no key generation, no account automation, no signup-flow tooling.

## Request flow

```text
Client
  -> FastAPI (gateway/app.py)
  -> Admin/Public route split
  -> /v1/chat/completions : auth? no (public, optional UAG_REQUIRE_AUTH) -> Router
  -> Router: ModelRegistry resolves model -> ordered provider attempts
  -> Per provider: KeyStore.pick (enabled, least failures, not cooling down)
  -> ProviderClient.chat / chat_stream via httpx (async, timeouts)
  -> On 429/5xx/timeout: exponential backoff retry, then next key, then next provider
  -> On 401/403: mark key failed (never retry same key), try next key
  -> On 400/404: fail fast, no retry (client error)
  -> Circuit breaker: provider with N consecutive failures -> cooldown, skipped
  -> UsageStore.record (tokens, latency, cost estimate, masked key id)
  -> Structured log with request_id (no secrets, no prompt bodies by default)
  -> Response (SSE passthrough for stream=true)
```

## Module layout

```text
gateway/
  config.py       Settings dataclass; loads config/gateway.json + UAG_* env overrides
  keystore.py     Encrypted API key storage (Fernet, key from UAG_MASTER_KEY or
                  generated into data/.master_key with 0600). Never returns raw
                  secrets except via get_secret(); all listings masked.
  providers.py    ProviderDef dataclass + ProviderClient (OpenAI-compatible HTTP,
                  async httpx, health_check). Registry built from Settings.
  registry.py     ModelDef dataclass + ModelRegistry (pricing, capabilities,
                  enabled, priority, fallbacks).
  router.py       Router: model resolution, ordered attempts, retries with
                  backoff, circuit breaker, key rotation. Bounded attempts only.
  usage.py        UsageStore: SQLite usage records, summaries (day/7d/30d/all),
                  cost math from registry pricing, always labeled estimates.
  health.py       Background health-check loop; per-provider status snapshots.
  logging_setup.py  Structured logging, request_id correlation, secret scrubbing.
  app.py          create_app(settings): public /v1/*, /healthz; /admin/* behind
                  Bearer admin token; serves dashboard static files.
  dashboard/      Static SPA: overview, providers, models, keys, usage, logs,
                  settings. Real data only, via /admin/*.
  cli.py          Cross-platform CLI: serve/status/providers/models/keys/health/
                  usage/config/test.
  watchdog.py     Standalone supervisor: polls /healthz + /admin/health, restarts
                  the gateway process with backoff, capped restarts, logs.
```

## Interface contract (cross-module, do not break)

### config.py
```python
@dataclass
class ProviderConfig:
    name: str                 # e.g. "kilo"
    display_name: str
    base_url: str             # e.g. "https://api.kilo.ai"
    chat_path: str = "/api/gateway/chat/completions"
    models_path: str = "/api/gateway/models"
    api_style: str = "openai"
    enabled: bool = True
    priority: int = 100       # lower = tried first
    timeout_s: float = 60.0
    max_retries: int = 2

@dataclass
class ModelConfig:
    id: str                   # e.g. "kilo-auto/free"
    provider: str             # provider name (preferred)
    display_name: str = ""
    context_window: int = 0
    input_price_per_1k: float = 0.0    # USD; 0 = unknown/free
    output_price_per_1k: float = 0.0
    capabilities: list = field(default_factory=list)
    enabled: bool = True
    priority: int = 100
    fallbacks: list = field(default_factory=list)  # other model ids

@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8008
    data_dir: str = "data"
    admin_token: str = ""             # required in prod; UAG_ADMIN_TOKEN
    require_public_auth: bool = False # if True, /v1/* needs Bearer admin token too
    cors_origins: list = field(default_factory=list)
    log_level: str = "INFO"
    default_timeout_s: float = 60.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown_s: int = 120
    key_cooldown_s: int = 60
    providers: list = field(default_factory=list)   # List[ProviderConfig]
    models: list = field(default_factory=list)      # List[ModelConfig]

def load_settings(config_path="config/gateway.json") -> Settings
```

### keystore.py
```python
@dataclass
class KeyMeta:
    id: str; provider: str; label: str; masked: str; enabled: bool
    created_at: str; last_used_at: str | None; last_error: str | None
    consecutive_failures: int; total_requests: int; total_errors: int
    cooling_until: float = 0  # epoch; 0 = not cooling

class KeyStore:
    def __init__(self, db_path: str, master_key: bytes): ...
    def add(self, provider: str, label: str, api_key: str) -> str  # returns id
    def list(self, provider: str | None = None) -> list[KeyMeta]
    def get(self, key_id: str) -> KeyMeta | None
    def get_secret(self, key_id: str) -> str      # raw secret, internal use only
    def set_enabled(self, key_id: str, enabled: bool) -> bool
    def remove(self, key_id: str) -> bool
    def record_success(self, key_id: str, latency_ms: float): ...
    def record_failure(self, key_id: str, error: str, cooldown_s: int = 60): ...
    def pick(self, provider: str) -> KeyMeta | None
        # enabled AND cooling_until <= now, lowest consecutive_failures then
        # oldest last_used_at. Returns None if no usable key.

def mask_secret(s: str) -> str   # "sk-••••••••abcd" (last 4)
def get_or_create_master_key(path: str) -> bytes  # 0600 file, Fernet key
```

### providers.py
```python
@dataclass
class ProviderDef:  # runtime view built from ProviderConfig
    name: str; base_url: str; chat_path: str; models_path: str
    enabled: bool; priority: int; timeout_s: float; max_retries: int

class ProviderError(Exception):
    def __init__(self, status: int | None, message: str, retryable: bool): ...

class ProviderClient:
    def __init__(self, definition: ProviderDef): ...
    async def chat(self, model: str, payload: dict, api_key: str, request_id: str) -> dict:
        """POST chat completions, non-streaming. Raises ProviderError."""
    async def chat_stream(self, model: str, payload: dict, api_key: str, request_id: str):
        """Async generator yielding raw SSE bytes. Raises ProviderError on HTTP error."""
    async def health_check(self, api_key: str | None = None) -> dict:
        """GET models_path (or base_url) -> {"ok": bool, "latency_ms": float, "detail": str}"""

def build_providers(settings: Settings) -> dict[str, ProviderClient]
```

### registry.py
```python
@dataclass
class ModelDef:  # runtime view built from ModelConfig
    id: str; provider: str; display_name: str; context_window: int
    input_price_per_1k: float; output_price_per_1k: float
    capabilities: list; enabled: bool; priority: int; fallbacks: list

class ModelRegistry:
    def __init__(self, models: list[ModelConfig]): ...
    def get(self, model_id: str) -> ModelDef | None
    def list(self, enabled_only: bool = False) -> list[ModelDef]
    def resolve(self, model_id: str) -> list[ModelDef]:
        """Ordered attempt list: the model itself (if enabled) then its
        fallbacks (enabled only). Empty list = unknown/disabled model."""
```

### router.py
```python
class RoutingError(Exception):
    def __init__(self, message: str, attempts: list[dict]): ...

class Router:
    def __init__(self, settings: Settings, keystore: KeyStore,
                 providers: dict[str, ProviderClient], registry: ModelRegistry,
                 usage /* UsageStore */, logger): ...
    async def complete(self, payload: dict, request_id: str) -> dict:
        """Non-streaming chat completion with full fallback. Raises RoutingError
        when every attempt is exhausted. Records usage + key outcomes."""
    async def complete_stream(self, payload: dict, request_id: str):
        """Async generator of SSE bytes; same routing/fallback rules, but once
        the first byte streams from a provider there is no provider fallback."""

# Attempt budget: attempts <= (models tried) * (keys tried per model, max 3)
# * (retries+1). Never unbounded. Retryable: 429, 5xx, timeouts, connection
# errors. Not retryable: 400, 401, 403, 404. 401/403 -> record key failure
# (key may be revoked) and move to next key.
```

### usage.py
```python
@dataclass
class UsageRecord:  # fields: ts, request_id, provider, model, key_id, key_masked,
                    # status ("ok"/"error"), latency_ms, prompt_tokens,
                    # completion_tokens, cost_usd, error

class UsageStore:
    def __init__(self, db_path: str): ...
    def record(self, rec: UsageRecord): ...
    def summary(self, days: int | None = None) -> dict:
        # {"totals": {...}, "by_provider": [...], "by_model": [...],
        #  "cost_estimated": True}
    def recent(self, limit: int = 100, status: str | None = None) -> list[dict]

def estimate_cost(prompt_tokens, completion_tokens, model_def) -> float
```

### health.py
```python
async def check_all(providers, keystore) -> dict[str, dict]
    # {"kilo": {"ok": bool, "latency_ms": float, "detail": str, "checked_at": str}}
async def health_loop(providers, keystore, interval_s, callback): ...
```

### app.py
```python
def create_app(settings: Settings | None = None) -> FastAPI
```
- `GET /healthz` -> {"status": "ok", ...} (no auth)
- `GET /v1/models` -> OpenAI-style list from registry (no auth unless require_public_auth)
- `POST /v1/chat/completions` -> router; honors `stream: true` (SSE)
- `GET /`, `GET /dashboard` -> static SPA
- `/admin/*` behind `Authorization: Bearer <admin_token>`:
  `GET /admin/status`, `/admin/providers`, `/admin/models`,
  `/admin/keys` (GET list, POST add {provider,label,api_key}),
  `/admin/keys/{id}` (PATCH enabled, DELETE),
  `/admin/usage` (?days=), `/admin/requests` (?limit=&status=),
  `/admin/health`, `/admin/logs` (?lines=), `/admin/config` (GET, sanitized)
- Every response carries `X-Request-ID`. Errors are OpenAI-style
  `{"error": {"message": ..., "type": ..., "code": ...}}`.
- No raw secrets in any response or log. Admin key add returns the KeyMeta
  (masked), never echoes the secret.

### cli.py
Commands: `serve`, `status`, `providers`, `models`, `keys add|list|enable|disable|remove`,
`health`, `usage [--days N]`, `config show`, `test` (runs pytest).
`python -m gateway.cli ...` from repo root. Never prints raw secrets.

### watchdog.py
`python gateway/watchdog.py [--config ...]`: polls `/healthz` and
`/admin/health` every N seconds (default 30); on consecutive failures restarts
the gateway subprocess (`python -m gateway.cli serve`); exponential backoff;
max 5 restarts per hour then stops trying and logs CRITICAL; PID file;
structured log file `data/watchdog.log`. Verified live 2026-09-27: SIGKILL of the
gateway -> restart as watchdog child after backoff, /healthz 200 on recovery.
Notes: on a fresh start with no gateway listening, the first child is spawned only
after the failure threshold + first backoff delay (the watchdog bootstraps, it does
not pre-start). A gateway that is "sick" but is NOT the watchdog's child is never
killed (manual intervention is logged instead). Single instance enforced via
`data/watchdog.lock`; SIGTERM stops the child and removes pid/lock files.

## Security rules (non-negotiable)
- API keys encrypted at rest (Fernet), masked everywhere else.
- Admin token required for all /admin/*; default bind 127.0.0.1.
- No prompt/response bodies in logs by default (counts only).
- Provider base_url allowlist: only http(s) URLs from config; validate on load.
- Input validation via pydantic on admin writes; chat payload passed through
  but size-capped (config max_request_bytes).
- Nothing in gateway/ imports from legacy/quarantine.
