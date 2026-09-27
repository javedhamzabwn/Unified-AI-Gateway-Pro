"""FastAPI application: public OpenAI-compatible API + admin API + dashboard.

BYOK gateway. No key generation, no account automation anywhere in this file.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hmac
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel

from .config import load_settings, Settings, ModelConfig
from .keystore import KeyStore, get_or_create_master_key
from .providers import build_providers
from .registry import ModelRegistry
from .router import Router, RoutingError
from .usage import UsageStore

VERSION = "2.0.0"
DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _error(message: str, *, status: int = 500, err_type: str = "server_error",
           code: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": err_type,
                           "code": code if code is not None else status}},
    )


def _get_logger(settings: Settings) -> logging.Logger:
    """Prefer gateway.logging_setup when available; fall back to stdlib.

    Agent A's setup_logging() only attaches a stdout handler, so we always
    ensure a FileHandler on data/gateway.log exists: /admin/logs reads it.
    """
    log_file = os.path.join(settings.data_dir, "gateway.log")
    logger: logging.Logger | None = None
    try:
        from . import logging_setup as _ls
        setup = getattr(_ls, "setup_logging", None)
        if callable(setup):
            try:
                logger = setup(level=settings.log_level)
            except TypeError:
                logger = setup()
    except Exception:
        logger = None
    if logger is None:
        logger = logging.getLogger("gateway")
        logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
        if not logger.handlers:
            sh = logging.StreamHandler()
            sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            logger.addHandler(sh)
    try:
        abs_log = os.path.abspath(log_file)
        already = any(
            isinstance(h, logging.FileHandler)
            and os.path.abspath(getattr(h, "baseFilename", "")) == abs_log
            for h in logger.handlers
        )
        if not already:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"))
            logger.addHandler(fh)
    except Exception:
        pass
    return logger


def _master_key(settings: Settings) -> bytes:
    env_key = os.environ.get("UAG_MASTER_KEY", "").strip()
    if env_key:
        # Must be a valid Fernet key (32 urlsafe-b64 bytes); invalid -> fail fast.
        return env_key.encode("utf-8")
    return get_or_create_master_key(os.path.join(settings.data_dir, ".master_key"))


def _config_path() -> str:
    return os.environ.get("UAG_CONFIG_PATH", os.path.join(os.getcwd(), "config", "gateway.json"))


def _persist_models(settings: Settings) -> None:
    """Write settings.models back to the JSON config, preserving other keys."""
    path = _config_path()
    raw: dict = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    raw["models"] = [dataclasses.asdict(m) for m in settings.models]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)


async def _require_admin(request: Request):
    settings: Settings = request.app.state.settings
    if not settings.admin_token:
        raise _AdminAuthError("admin API disabled: no admin token configured")
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise _AdminAuthError("missing bearer token")
    token = auth[7:].strip()
    if not token or not hmac.compare_digest(token, settings.admin_token):
        raise _AdminAuthError("invalid admin token")
    return True


class _AdminAuthError(Exception):
    pass


async def _health_loop(app: FastAPI, run_immediately: bool = False):
    if run_immediately:
        try:
            from .health import check_all
            app.state.health_snapshot = await check_all(
                app.state.providers, app.state.keystore)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never kill the loop
            app.state.logger.warning("health check failed: %s", exc)
    while True:
        await asyncio.sleep(60)
        try:
            from .health import check_all
            app.state.health_snapshot = await check_all(
                app.state.providers, app.state.keystore)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never kill the loop
            app.state.logger.warning("health check failed: %s", exc)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Never block startup on network I/O: run the first health check in the
    # background so the server accepts traffic immediately even if provider
    # endpoints are slow or unreachable.
    app.state.health_snapshot = {}
    task = asyncio.create_task(_health_loop(app, run_immediately=True))
    app.state.logger.info("gateway started (v%s, pid %s)", VERSION, os.getpid())
    try:
        yield
    finally:
        task.cancel()
        app.state.logger.info("gateway stopping")


# --------------------------------------------------------------------------- #
# pydantic bodies for admin writes
# --------------------------------------------------------------------------- #
class KeyAddRequest(BaseModel):
    provider: str
    label: str
    api_key: str


class KeyPatchRequest(BaseModel):
    enabled: bool


class ModelAddRequest(BaseModel):
    id: str
    provider: str
    display_name: str = ""
    context_window: int = 0
    input_price_per_1k: float = 0.0
    output_price_per_1k: float = 0.0
    capabilities: list = []
    enabled: bool = True
    priority: int = 100
    fallbacks: list = []


class ModelPatchRequest(BaseModel):
    enabled: bool | None = None
    priority: int | None = None
    display_name: str | None = None
    context_window: int | None = None
    input_price_per_1k: float | None = None
    output_price_per_1k: float | None = None
    capabilities: list | None = None
    fallbacks: list | None = None


# --------------------------------------------------------------------------- #
# app factory
# --------------------------------------------------------------------------- #
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    os.makedirs(settings.data_dir, exist_ok=True)
    logger = _get_logger(settings)

    keystore = KeyStore(os.path.join(settings.data_dir, "keys.db"), _master_key(settings))
    providers = build_providers(settings)
    registry = ModelRegistry(settings.models)
    usage = UsageStore(os.path.join(settings.data_dir, "usage.db"))
    router = Router(settings, keystore, providers, registry, usage, logger)

    app = FastAPI(title="Unified AI Gateway Pro", version=VERSION, lifespan=_lifespan)
    app.state.settings = settings
    app.state.logger = logger
    app.state.keystore = keystore
    app.state.providers = providers
    app.state.registry = registry
    app.state.usage = usage
    app.state.router = router
    app.state.started_at = time.time()
    app.state.health_snapshot = {}

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def _request_id_middleware(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(_AdminAuthError)
    async def _admin_auth_handler(request: Request, exc: _AdminAuthError):
        return _error(str(exc), status=401, err_type="auth_error", code=401)

    # ---------------- public API ---------------- #
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok", "version": VERSION, "time": time.time()}

    def _public_auth_ok(request: Request) -> bool:
        if not settings.require_public_auth:
            return True
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return False
        return bool(settings.admin_token) and hmac.compare_digest(
            auth[7:].strip(), settings.admin_token)

    @app.get("/v1/models")
    async def list_models(request: Request):
        if not _public_auth_ok(request):
            return _error("unauthorized", status=401, err_type="auth_error", code=401)
        created = int(app.state.started_at)
        data = [
            {"id": m.id, "object": "model", "owned_by": m.provider, "created": created}
            for m in app.state.registry.list(enabled_only=True)
        ]
        return {"object": "list", "data": data}

    async def _sse_gen(body: dict, request_id: str):
        seen_done = False
        try:
            async for chunk in app.state.router.complete_stream(body, request_id):
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                if b"[DONE]" in chunk:
                    seen_done = True
                yield chunk
        except RoutingError as exc:
            payload = {"error": {"message": str(exc), "type": "server_error",
                                 "code": "all_providers_failed"}}
            yield ("data: " + json.dumps(payload) + "\n\n").encode("utf-8")
        if not seen_done:
            yield b"data: [DONE]\n\n"

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        rid = request.state.request_id
        if not _public_auth_ok(request):
            return _error("unauthorized", status=401, err_type="auth_error", code=401)
        raw = await request.body()
        if len(raw) > settings.max_request_bytes:
            return _error("request body too large", status=413,
                          err_type="invalid_request_error", code=413)
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            return _error("invalid JSON body", status=400,
                          err_type="invalid_request_error", code=400)
        if not isinstance(body, dict):
            return _error("request body must be a JSON object", status=400,
                          err_type="invalid_request_error", code=400)
        if not isinstance(body.get("model"), str) or not body["model"].strip():
            return _error("'model' is required and must be a string", status=400,
                          err_type="invalid_request_error", code=400)
        if not isinstance(body.get("messages"), list) or not body["messages"]:
            return _error("'messages' is required and must be a non-empty list",
                          status=400, err_type="invalid_request_error", code=400)

        # fail fast on unknown/disabled model before opening a stream.
        # NB: check the requested model itself, not resolve(): a disabled
        # model with enabled fallbacks must still 404, not serve via fallback.
        _primary = app.state.registry.get(body["model"])
        if _primary is None or not _primary.enabled:
            return _error(f"model '{body['model']}' not found or disabled",
                          status=404, err_type="model_not_found", code=404)

        try:
            if body.get("stream"):
                return StreamingResponse(
                    _sse_gen(body, rid),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"},
                )
            result = await app.state.router.complete(body, rid)
            return JSONResponse(result)
        except RoutingError as exc:
            logger.warning("[%s] routing failed for model %s: %s",
                           rid, body.get("model"), exc)
            return _error(str(exc),
                          status=502, err_type="server_error",
                          code="all_providers_failed")
        except Exception as exc:  # never leak internals
            logger.exception("[%s] unexpected error: %s", rid, exc)
            return _error("internal server error", status=500)

    # ---------------- dashboard static ---------------- #
    @app.get("/", include_in_schema=False)
    @app.get("/dashboard", include_in_schema=False)
    async def _dashboard_index():
        return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))

    @app.get("/app.js", include_in_schema=False)
    async def _dashboard_js():
        return FileResponse(os.path.join(DASHBOARD_DIR, "app.js"),
                            media_type="application/javascript")

    @app.get("/style.css", include_in_schema=False)
    async def _dashboard_css():
        return FileResponse(os.path.join(DASHBOARD_DIR, "style.css"),
                            media_type="text/css")

    # ---------------- admin API ---------------- #
    admin = APIRouter(prefix="/admin", dependencies=[Depends(_require_admin)])

    @admin.get("/status")
    async def admin_status(request: Request):
        snap = request.app.state.health_snapshot or {}
        prov_names = list(request.app.state.providers)
        all_bad = bool(prov_names) and all(
            isinstance(snap.get(n), dict) and not snap.get(n, {}).get("ok")
            for n in prov_names)
        ks = request.app.state.keystore
        return {
            "status": "degraded" if all_bad else "ok",
            "version": VERSION,
            "uptime_s": round(time.time() - request.app.state.started_at, 1),
            "pid": os.getpid(),
            "providers_total": len(prov_names),
            "providers_enabled": sum(
                1 for c in request.app.state.providers.values()
                if c.definition.enabled),
            "keys_total": sum(len(ks.list(p)) for p in prov_names),
            "models_total": len(request.app.state.registry.list()),
            "models_enabled": len(request.app.state.registry.list(enabled_only=True)),
            "health_loop": "running",
            "data_dir": settings.data_dir,
        }

    @admin.get("/providers")
    async def admin_providers(request: Request):
        snap = request.app.state.health_snapshot or {}
        ks = request.app.state.keystore
        reg = request.app.state.registry
        out = []
        for name, client in request.app.state.providers.items():
            d = dataclasses.asdict(client.definition)
            d["health"] = snap.get(name)
            d["key_count"] = len(ks.list(name))
            d["model_count"] = sum(
                1 for m in reg.list() if m.provider == name)
            out.append(d)
        return {"providers": out}

    @admin.get("/models")
    async def admin_models(request: Request):
        return {"models": [dataclasses.asdict(m)
                           for m in request.app.state.registry.list()]}

    def _refresh_registry(request: Request):
        _persist_models(settings)
        request.app.state.registry = ModelRegistry(settings.models)

    @admin.post("/models")
    async def admin_model_upsert(body: ModelAddRequest, request: Request):
        if body.provider not in request.app.state.providers:
            return _error(f"unknown provider '{body.provider}'", status=400,
                          err_type="invalid_request_error", code=400)
        existing = next((m for m in settings.models if m.id == body.id), None)
        if existing:
            for f in ("provider", "display_name", "context_window",
                      "input_price_per_1k", "output_price_per_1k",
                      "capabilities", "enabled", "priority", "fallbacks"):
                setattr(existing, f, getattr(body, f))
        else:
            settings.models.append(ModelConfig(**body.model_dump()))
        _refresh_registry(request)
        model = request.app.state.registry.get(body.id)
        return {"model": dataclasses.asdict(model)}

    @admin.patch("/models/{model_id:path}")
    async def admin_model_patch(model_id: str, body: ModelPatchRequest,
                               request: Request):
        existing = next((m for m in settings.models if m.id == model_id), None)
        if existing is None:
            return _error(f"model '{model_id}' not found", status=404,
                          err_type="model_not_found", code=404)
        for f, v in body.model_dump().items():
            if v is not None:
                setattr(existing, f, v)
        _refresh_registry(request)
        return {"model": dataclasses.asdict(
            request.app.state.registry.get(model_id))}

    @admin.get("/keys")
    async def admin_keys(request: Request, provider: str | None = None):
        ks = request.app.state.keystore
        if provider and provider not in request.app.state.providers:
            return _error(f"unknown provider '{provider}'", status=400,
                          err_type="invalid_request_error", code=400)
        return {"keys": [dataclasses.asdict(k) for k in ks.list(provider)]}

    @admin.post("/keys")
    async def admin_key_add(body: KeyAddRequest, request: Request):
        if body.provider not in request.app.state.providers:
            return _error(f"unknown provider '{body.provider}'", status=400,
                          err_type="invalid_request_error", code=400)
        label = body.label.strip()
        if not label:
            return _error("'label' is required", status=400,
                          err_type="invalid_request_error", code=400)
        if not isinstance(body.api_key, str) or len(body.api_key) < 8:
            return _error("'api_key' must be a string of at least 8 characters",
                          status=400, err_type="invalid_request_error", code=400)
        ks = request.app.state.keystore
        key_id = ks.add(body.provider, label, body.api_key)
        meta = ks.get(key_id)
        # never echo the secret back
        return {"key": dataclasses.asdict(meta)}

    @admin.patch("/keys/{key_id}")
    async def admin_key_patch(key_id: str, body: KeyPatchRequest, request: Request):
        ks = request.app.state.keystore
        if ks.get(key_id) is None:
            return _error(f"key '{key_id}' not found", status=404,
                          err_type="not_found", code=404)
        ks.set_enabled(key_id, body.enabled)
        return {"key": dataclasses.asdict(ks.get(key_id))}

    @admin.delete("/keys/{key_id}")
    async def admin_key_delete(key_id: str, request: Request):
        ks = request.app.state.keystore
        if not ks.remove(key_id):
            return _error(f"key '{key_id}' not found", status=404,
                          err_type="not_found", code=404)
        return {"deleted": key_id}

    @admin.get("/usage")
    async def admin_usage(request: Request, days: str = "30"):
        try:
            d = None if days.lower() in ("all", "0", "none") else int(days)
            if d is not None and d < 0:
                raise ValueError
        except ValueError:
            return _error("'days' must be a non-negative integer or 'all'",
                          status=400, err_type="invalid_request_error", code=400)
        return request.app.state.usage.summary(d)

    @admin.get("/requests")
    async def admin_requests(request: Request, limit: int = 100,
                             status: str | None = None):
        limit = max(1, min(limit, 1000))
        if status not in (None, "ok", "error"):
            return _error("'status' must be 'ok' or 'error'", status=400,
                          err_type="invalid_request_error", code=400)
        return {"requests": request.app.state.usage.recent(limit=limit,
                                                           status=status)}

    @admin.get("/health")
    async def admin_health(request: Request):
        return {"providers": request.app.state.health_snapshot or {}}

    @admin.get("/logs")
    async def admin_logs(request: Request, lines: int = 200):
        lines = max(1, min(lines, 2000))
        path = os.path.join(settings.data_dir, "gateway.log")
        if not os.path.exists(path):
            return {"lines": []}
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.readlines()
        return {"lines": [ln.rstrip("\n") for ln in content[-lines:]]}

    @admin.get("/config")
    async def admin_config():
        d = dataclasses.asdict(settings)
        d["admin_token"] = None
        d["admin_token_configured"] = bool(settings.admin_token)
        return {"config": d}

    app.include_router(admin)

    if not settings.admin_token:
        logger.warning("UAG_ADMIN_TOKEN not set: /admin/* will reject all "
                       "requests until a token is configured")

    return app
