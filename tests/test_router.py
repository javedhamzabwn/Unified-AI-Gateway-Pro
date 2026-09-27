"""Router tests: fallback, fast failure, key rotation, circuit breaker, bounds."""
import dataclasses
import logging

import pytest

import gateway.router as _router_module
from gateway.providers import ProviderError
from gateway.registry import ModelRegistry
from gateway.router import Router, RoutingError
from gateway.usage import UsageStore

from conftest import CHAT_PAYLOAD, OK_CHAT_RESPONSE


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Router backoff sleeps must not slow the suite."""

    async def _fast(_seconds):
        return None

    monkeypatch.setattr(_router_module.asyncio, "sleep", _fast)


class _FakeDef:
    def __init__(self, name, max_retries=0, enabled=True):
        self.name = name
        self.max_retries = max_retries
        self.enabled = enabled


class FakeProviderClient:
    """Scripted provider client. script = list of ("ok", resp) or ("err", exc)."""

    def __init__(self, name, script, max_retries=0):
        self.definition = _FakeDef(name, max_retries)
        self._script = list(script)
        self.calls = 0

    async def chat(self, model, payload, api_key, request_id):
        self.calls += 1
        if not self._script:
            raise ProviderError(500, "script exhausted", True)
        kind, value = self._script.pop(0)
        if kind == "ok":
            return value
        raise value

    async def chat_stream(self, model, payload, api_key, request_id):
        raise ProviderError(500, "no stream in fake", True)

    async def health_check(self, api_key=None):
        return {"ok": True, "latency_ms": 1.0, "detail": "fake"}


def _router(settings, keystore, tmp_data, scripts, max_retries=0):
    providers = {}
    for name, script in scripts.items():
        providers[name] = FakeProviderClient(name, script,
                                             max_retries=max_retries)
    registry = ModelRegistry(settings.models)
    usage = UsageStore(__import__("os").path.join(tmp_data, "usage.db"))
    logger = logging.getLogger("test-router")
    return Router(settings, keystore, providers, registry, usage, logger), providers


@pytest.mark.asyncio
async def test_429_falls_back_to_next_provider(test_settings, keystore,
                                               tmp_data):
    router, fakes = _router(
        test_settings, keystore, tmp_data,
        {"p1": [("err", ProviderError(429, "rate limited", True))],
         "p2": [("ok", OK_CHAT_RESPONSE)]})
    keystore.add("p1", "a", "sk-key-aaaa1111")
    keystore.add("p2", "b", "sk-key-bbbb2222")
    result = await router.complete(dict(CHAT_PAYLOAD), "r-429")
    assert result["id"] == "chatcmpl-test"
    assert fakes["p1"].calls == 1
    assert fakes["p2"].calls == 1


@pytest.mark.asyncio
async def test_400_fails_fast_with_single_attempt(test_settings, keystore,
                                                  tmp_data):
    router, fakes = _router(
        test_settings, keystore, tmp_data,
        {"p1": [("err", ProviderError(400, "bad request", False))],
         "p2": [("ok", OK_CHAT_RESPONSE)]})
    keystore.add("p1", "a", "sk-key-aaaa1111")
    keystore.add("p2", "b", "sk-key-bbbb2222")
    with pytest.raises(RoutingError) as exc_info:
        await router.complete(dict(CHAT_PAYLOAD), "r-400")
    assert len(exc_info.value.attempts) == 1
    assert exc_info.value.attempts[0]["status"] == 400
    # no retry, no fallback: p2 never touched
    assert fakes["p1"].calls == 1
    assert fakes["p2"].calls == 0


@pytest.mark.asyncio
async def test_401_rotates_to_next_key(test_settings, keystore, tmp_data):
    router, fakes = _router(
        test_settings, keystore, tmp_data,
        {"p1": [("err", ProviderError(401, "unauthorized", False)),
                ("ok", OK_CHAT_RESPONSE)],
         "p2": [("ok", OK_CHAT_RESPONSE)]})
    k1 = keystore.add("p1", "a", "sk-key-aaaa1111")
    keystore.add("p1", "b", "sk-key-bbbb2222")
    result = await router.complete(dict(CHAT_PAYLOAD), "r-401")
    assert result["id"] == "chatcmpl-test"
    assert fakes["p1"].calls == 2
    # the first key took the 401 and recorded a failure
    assert keystore.get(k1).consecutive_failures == 1
    # same provider reused after rotation, no fallback model needed
    assert fakes["p2"].calls == 0


@pytest.mark.asyncio
async def test_circuit_breaker_skips_open_provider(no_cooldown_settings,
                                                   keystore, tmp_data):
    err = lambda: ProviderError(500, "server error", True)  # noqa: E731
    router, fakes = _router(
        no_cooldown_settings, keystore, tmp_data,
        {"p1": [("err", err()) for _ in range(30)],
         "p2": [("err", err()) for _ in range(30)]})
    keystore.add("p1", "a", "sk-key-aaaa1111")
    keystore.add("p2", "b", "sk-key-bbbb2222")
    with pytest.raises(RoutingError):
        await router.complete(dict(CHAT_PAYLOAD), "r-cb1")
    # breaker threshold is 2: the next call must skip p1 entirely
    with pytest.raises(RoutingError) as exc_info:
        await router.complete(dict(CHAT_PAYLOAD), "r-cb2")
    real_p1 = [a for a in exc_info.value.attempts
               if a.get("provider") == "p1" and not a.get("skipped")]
    assert real_p1 == []


@pytest.mark.asyncio
async def test_attempts_are_bounded(no_cooldown_settings, keystore, tmp_data):
    settings = dataclasses.replace(no_cooldown_settings,
                                   circuit_breaker_threshold=1000)
    err = lambda: ProviderError(500, "server error", True)  # noqa: E731
    router, _ = _router(
        settings, keystore, tmp_data,
        {"p1": [("err", err()) for _ in range(100)],
         "p2": [("err", err()) for _ in range(100)]},
        max_retries=1)
    keystore.add("p1", "a", "sk-key-aaaa1111")
    keystore.add("p2", "b", "sk-key-bbbb2222")
    with pytest.raises(RoutingError) as exc_info:
        await router.complete(dict(CHAT_PAYLOAD), "r-bound")
    attempts = exc_info.value.attempts
    # 2 models x 3 keys per model x (1 + 1 retries)
    assert len(attempts) <= 2 * 3 * 2
    assert len(attempts) > 0


@pytest.mark.asyncio
async def test_unknown_model_raises_immediately(test_settings, keystore,
                                                tmp_data):
    router, fakes = _router(test_settings, keystore, tmp_data, {"p1": [], "p2": []})
    keystore.add("p1", "a", "sk-key-aaaa1111")
    with pytest.raises(RoutingError) as exc_info:
        await router.complete({"model": "nope",
                               "messages": CHAT_PAYLOAD["messages"]}, "r-unk")
    assert exc_info.value.attempts == []
    assert fakes["p1"].calls == 0


@pytest.mark.asyncio
async def test_429_respects_max_retries(no_cooldown_settings, keystore,
                                        tmp_data):
    router, fakes = _router(
        no_cooldown_settings, keystore, tmp_data,
        {"p1": [("err", ProviderError(429, "slow down", True)),
                ("ok", OK_CHAT_RESPONSE)],
         "p2": [("ok", OK_CHAT_RESPONSE)]},
        max_retries=1)
    keystore.add("p1", "a", "sk-key-aaaa1111")
    keystore.add("p2", "b", "sk-key-bbbb2222")
    result = await router.complete(dict(CHAT_PAYLOAD), "r-retry")
    assert result["id"] == "chatcmpl-test"
    assert fakes["p1"].calls == 2
    assert fakes["p2"].calls == 0


def test_provider_client_ignores_ambient_proxy_env(monkeypatch):
    """Regression: a malformed proxy env var must not break provider calls."""
    from gateway.providers import ProviderClient, ProviderDef

    monkeypatch.setenv("HTTPS_PROXY", "http://[::1]:1]")
    monkeypatch.setenv("https_proxy", "http://[::1]:1]")
    definition = ProviderDef(
        name="kilo", base_url="https://api.kilo.ai", chat_path="/x",
        models_path="/y", enabled=True, priority=100,
        timeout_s=5.0, max_retries=0,
    )
    client = ProviderClient(definition)
    inner = client._get_client()
    assert inner is not None
    assert client._client.trust_env is False
