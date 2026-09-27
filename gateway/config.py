"""Settings: config/gateway.json + UAG_* environment overrides."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class ProviderConfig:
    name: str
    display_name: str
    base_url: str
    chat_path: str = "/api/gateway/chat/completions"
    models_path: str = "/api/gateway/models"
    api_style: str = "openai"
    enabled: bool = True
    priority: int = 100
    timeout_s: float = 60.0
    max_retries: int = 2


@dataclass
class ModelConfig:
    id: str
    provider: str
    display_name: str = ""
    context_window: int = 0
    input_price_per_1k: float = 0.0
    output_price_per_1k: float = 0.0
    capabilities: list = field(default_factory=list)
    enabled: bool = True
    priority: int = 100
    fallbacks: list = field(default_factory=list)


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8008
    data_dir: str = "data"
    admin_token: str = ""
    require_public_auth: bool = False
    cors_origins: list = field(default_factory=list)
    log_level: str = "INFO"
    default_timeout_s: float = 60.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown_s: int = 120
    key_cooldown_s: int = 60
    max_request_bytes: int = 10_000_000
    providers: list = field(default_factory=list)  # List[ProviderConfig]
    models: list = field(default_factory=list)    # List[ModelConfig]


def _validate_provider_cfg(raw: dict) -> ProviderConfig:
    url = (raw.get("base_url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"provider '{raw.get('name')}' has invalid base_url: {url!r}")
    chat_path = raw.get("chat_path", "/api/gateway/chat/completions") or "/"
    if not chat_path.startswith("/"):
        raise ValueError(f"provider '{raw.get('name')}' chat_path must start with '/': {chat_path!r}")
    return ProviderConfig(
        name=str(raw["name"]),
        display_name=str(raw.get("display_name", raw["name"])),
        base_url=url,
        chat_path=chat_path,
        models_path=str(raw.get("models_path", "/api/gateway/models")),
        api_style=str(raw.get("api_style", "openai")),
        enabled=bool(raw.get("enabled", True)),
        priority=int(raw.get("priority", 100)),
        timeout_s=float(raw.get("timeout_s", 60.0)),
        max_retries=int(raw.get("max_retries", 2)),
    )


def _validate_model_cfg(raw: dict) -> ModelConfig:
    return ModelConfig(
        id=str(raw["id"]),
        provider=str(raw["provider"]),
        display_name=str(raw.get("display_name", "")),
        context_window=int(raw.get("context_window", 0)),
        input_price_per_1k=float(raw.get("input_price_per_1k", 0.0)),
        output_price_per_1k=float(raw.get("output_price_per_1k", 0.0)),
        capabilities=list(raw.get("capabilities", [])),
        enabled=bool(raw.get("enabled", True)),
        priority=int(raw.get("priority", 100)),
        fallbacks=list(raw.get("fallbacks", [])),
    )


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def load_settings(config_path: str = "config/gateway.json") -> Settings:
    """Load settings from JSON config file, then apply UAG_* env overrides."""
    raw: dict = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

    providers = [_validate_provider_cfg(p) for p in raw.get("providers", [])]
    models = [_validate_model_cfg(m) for m in raw.get("models", [])]

    s = Settings(
        host=str(raw.get("host", "127.0.0.1")),
        port=int(raw.get("port", 8008)),
        data_dir=str(raw.get("data_dir", "data")),
        admin_token=str(raw.get("admin_token", "")),
        require_public_auth=bool(raw.get("require_public_auth", False)),
        cors_origins=list(raw.get("cors_origins", [])),
        log_level=str(raw.get("log_level", "INFO")),
        default_timeout_s=float(raw.get("default_timeout_s", 60.0)),
        circuit_breaker_threshold=int(raw.get("circuit_breaker_threshold", 5)),
        circuit_breaker_cooldown_s=int(raw.get("circuit_breaker_cooldown_s", 120)),
        key_cooldown_s=int(raw.get("key_cooldown_s", 60)),
        max_request_bytes=int(raw.get("max_request_bytes", 10_000_000)),
        providers=providers,
        models=models,
    )

    # Environment overrides (UAG_*)
    if os.environ.get("UAG_HOST"):
        s.host = os.environ["UAG_HOST"]
    if os.environ.get("UAG_PORT"):
        s.port = int(os.environ["UAG_PORT"])
    if os.environ.get("UAG_DATA_DIR"):
        s.data_dir = os.environ["UAG_DATA_DIR"]
    if os.environ.get("UAG_ADMIN_TOKEN"):
        s.admin_token = os.environ["UAG_ADMIN_TOKEN"]
    if os.environ.get("UAG_LOG_LEVEL"):
        s.log_level = os.environ["UAG_LOG_LEVEL"].upper()
    s.require_public_auth = _env_bool("UAG_REQUIRE_PUBLIC_AUTH", s.require_public_auth)

    return s
