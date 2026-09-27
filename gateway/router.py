"""Routing engine: model resolution, key rotation, retries, circuit breaker.

Rules (per ARCHITECTURE.md):
- Resolve model -> ordered model attempts (primary, then enabled fallbacks).
- Per model: its provider; try up to 3 keys from KeyStore.pick().
- Per key: up to (max_retries + 1) attempts on retryable errors (429/5xx/
  timeout/connection) with exponential backoff 0.5s * 2^n capped at 8s.
- 401/403: record key failure (cooldown), move to next key, never retry same key.
- 400/404/other non-retryable: fail fast, no retry at all.
- Circuit breaker: provider with `circuit_breaker_threshold` consecutive
  retryable failures is skipped for `circuit_breaker_cooldown_s` seconds.
  Auth failures do NOT trip the breaker (key-level problem, not provider-level).
- complete_stream(): same routing, but once the first byte streams from a
  provider there is no further fallback (documented limitation).
"""
from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from .logging_setup import set_request_id
from .providers import ProviderError
from .usage import UsageRecord, estimate_cost


class RoutingError(Exception):
    def __init__(self, message: str, attempts: list[dict]):
        super().__init__(message)
        self.message = message
        self.attempts = attempts


_MAX_KEYS_PER_MODEL = 3
_BACKOFF_BASE_S = 0.5
_BACKOFF_CAP_S = 8.0


class Router:
    def __init__(self, settings, keystore, providers: dict, registry, usage, logger):
        self.settings = settings
        self.keystore = keystore
        self.providers = providers
        self.registry = registry
        self.usage = usage
        self.logger = logger
        # circuit breaker state: provider -> {"failures": int, "open_until": float}
        self._breaker: dict[str, dict] = {}

    # -- circuit breaker -------------------------------------------------
    def _breaker_state(self, provider: str) -> dict:
        return self._breaker.setdefault(provider, {"failures": 0, "open_until": 0.0})

    def _breaker_open(self, provider: str) -> bool:
        st = self._breaker_state(provider)
        if st["open_until"] > time.time():
            return True
        if st["open_until"] and st["open_until"] <= time.time():
            st["open_until"] = 0.0  # cooldown elapsed; half-open (allow one attempt)
        return False

    def _breaker_success(self, provider: str) -> None:
        st = self._breaker_state(provider)
        st["failures"] = 0
        st["open_until"] = 0.0

    def _breaker_failure(self, provider: str) -> None:
        st = self._breaker_state(provider)
        st["failures"] += 1
        if st["failures"] >= max(1, self.settings.circuit_breaker_threshold):
            st["open_until"] = time.time() + max(1, self.settings.circuit_breaker_cooldown_s)
            self.logger.warning(
                "circuit breaker OPEN for provider '%s' (%d consecutive failures)",
                provider, st["failures"],
            )

    # -- usage ------------------------------------------------------------
    def _extract_usage(self, response: dict) -> tuple[int, int]:
        u = (response or {}).get("usage") or {}
        try:
            return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
        except (TypeError, ValueError):
            return 0, 0

    def _record_usage(self, request_id: str, provider: str, model_id: str,
                      key_id: str, key_masked: str, status: str,
                      latency_ms: float, prompt_tokens: int,
                      completion_tokens: int, error: str | None) -> None:
        model_def = self.registry.get(model_id)
        cost = estimate_cost(prompt_tokens, completion_tokens, model_def) if status == "ok" else 0.0
        try:
            self.usage.record(UsageRecord(
                ts=time.time(), request_id=request_id, provider=provider, model=model_id,
                key_id=key_id, key_masked=key_masked, status=status,
                latency_ms=latency_ms, prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens, cost_usd=cost, error=error,
            ))
        except Exception as e:
            self.logger.error("usage record failed: %s", e)

    # -- core attempt logic ------------------------------------------------
    async def _attempt_with_retries(self, client, model_id: str, payload: dict,
                                    secret: str, request_id: str,
                                    attempts: list[dict], max_retries: int) -> tuple[dict, float]:
        """Try one key with bounded retries. Returns (response, latency_ms).
        Raises ProviderError when retries are exhausted or error not retryable."""
        last_err: ProviderError | None = None
        t0 = time.perf_counter()
        for n in range(max_retries + 1):
            try:
                resp = await client.chat(model_id, payload, secret, request_id)
                return resp, (time.perf_counter() - t0) * 1000
            except ProviderError as e:
                last_err = e
                attempts.append({
                    "provider": client.definition.name, "model": model_id,
                    "status": e.status, "retryable": e.retryable,
                    "attempt": n + 1, "error": e.message[:200],
                })
                if not e.retryable:
                    raise
                if n < max_retries:
                    delay = min(_BACKOFF_BASE_S * (2 ** n), _BACKOFF_CAP_S)
                    await asyncio.sleep(delay)
        assert last_err is not None
        raise last_err

    async def complete(self, payload: dict, request_id: str) -> dict:
        set_request_id(request_id)
        model_id = (payload or {}).get("model", "")
        primary = self.registry.get(model_id)
        attempts: list[dict] = []
        if primary is None or not primary.enabled:
            raise RoutingError(f"unknown or disabled model '{model_id}'", attempts)
        resolved = self.registry.resolve(model_id)
        if not resolved:
            raise RoutingError(f"unknown or disabled model '{model_id}'", attempts)

        overall_t0 = time.perf_counter()
        for mdef in resolved:
            provider_name = mdef.provider
            client = self.providers.get(provider_name)
            if client is None or not client.definition.enabled:
                attempts.append({"provider": provider_name, "model": mdef.id,
                                 "skipped": "provider not configured/enabled"})
                continue
            if self._breaker_open(provider_name):
                attempts.append({"provider": provider_name, "model": mdef.id,
                                 "skipped": "circuit breaker open"})
                self.logger.warning("skipping provider '%s': circuit breaker open", provider_name)
                continue

            keys_tried = 0
            while keys_tried < _MAX_KEYS_PER_MODEL:
                key = self.keystore.pick(provider_name)
                if key is None:
                    attempts.append({"provider": provider_name, "model": mdef.id,
                                     "skipped": "no usable keys"})
                    break
                keys_tried += 1
                try:
                    secret = self.keystore.get_secret(key.id)
                except Exception as e:
                    attempts.append({"provider": provider_name, "model": mdef.id,
                                     "key": key.masked, "error": f"secret unreadable: {e}"})
                    continue
                try:
                    resp, latency_ms = await self._attempt_with_retries(
                        client, mdef.id, payload, secret, request_id, attempts,
                        max_retries=max(0, client.definition.max_retries),
                    )
                    self._breaker_success(provider_name)
                    self.keystore.record_success(key.id, latency_ms)
                    pt, ct = self._extract_usage(resp)
                    self._record_usage(request_id, provider_name, mdef.id, key.id,
                                       key.masked, "ok", latency_ms, pt, ct, None)
                    self.logger.info("served model '%s' via %s key %s (%.0fms)",
                                     mdef.id, provider_name, key.masked, latency_ms)
                    return resp
                except ProviderError as e:
                    if e.status in (401, 403):
                        # Key-level auth problem: cool the key down, try next key.
                        self.keystore.record_failure(
                            key.id, f"auth failure ({e.status})",
                            cooldown_s=self.settings.key_cooldown_s)
                        self.logger.warning("key %s auth failed (%s); rotating key",
                                            key.masked, e.status)
                        continue
                    if not e.retryable:
                        # 400/404 etc: client error, fail fast, no retry at all.
                        latency_ms = (time.perf_counter() - overall_t0) * 1000
                        self._record_usage(request_id, provider_name, mdef.id, key.id,
                                           key.masked, "error", latency_ms, 0, 0, e.message)
                        raise RoutingError(f"request failed: {e.message}", attempts) from e
                    # Retryable but retries exhausted for this key: cool it down,
                    # count a provider-level failure, try the next key.
                    self.keystore.record_failure(
                        key.id, e.message, cooldown_s=self.settings.key_cooldown_s)
                    self._breaker_failure(provider_name)
                    self.logger.warning("key %s failed (%s); trying next key",
                                        key.masked, e.message[:120])
                    continue
            # next resolved model (fallback)

        latency_ms = (time.perf_counter() - overall_t0) * 1000
        last_provider = attempts[-1].get("provider", "") if attempts else ""
        self._record_usage(request_id, last_provider, model_id, "", "", "error",
                           latency_ms, 0, 0, "all providers exhausted")
        raise RoutingError(
            f"failed to serve model '{model_id}': all providers/keys exhausted", attempts)

    async def complete_stream(self, payload: dict, request_id: str) -> AsyncIterator[bytes]:
        """Streaming variant. Same routing/fallback rules apply while selecting
        a provider, but once the first byte has streamed from a provider there
        is no further fallback: mid-stream errors are logged and re-raised."""
        set_request_id(request_id)
        model_id = (payload or {}).get("model", "")
        primary = self.registry.get(model_id)
        attempts: list[dict] = []
        if primary is None or not primary.enabled:
            raise RoutingError(f"unknown or disabled model '{model_id}'", attempts)
        resolved = self.registry.resolve(model_id)
        if not resolved:
            raise RoutingError(f"unknown or disabled model '{model_id}'", attempts)

        overall_t0 = time.perf_counter()
        for mdef in resolved:
            provider_name = mdef.provider
            client = self.providers.get(provider_name)
            if client is None or not client.definition.enabled:
                continue
            if self._breaker_open(provider_name):
                continue
            keys_tried = 0
            while keys_tried < _MAX_KEYS_PER_MODEL:
                key = self.keystore.pick(provider_name)
                if key is None:
                    break
                keys_tried += 1
                try:
                    secret = self.keystore.get_secret(key.id)
                except Exception:
                    continue
                t0 = time.perf_counter()
                streaming = False
                try:
                    async for chunk in client.chat_stream(mdef.id, payload, secret, request_id):
                        streaming = True
                        yield chunk
                    # stream completed cleanly
                    latency_ms = (time.perf_counter() - t0) * 1000
                    self._breaker_success(provider_name)
                    self.keystore.record_success(key.id, latency_ms)
                    self._record_usage(request_id, provider_name, mdef.id, key.id,
                                       key.masked, "ok", latency_ms, 0, 0, None)
                    return
                except ProviderError as e:
                    attempts.append({
                        "provider": provider_name, "model": mdef.id,
                        "status": e.status, "retryable": e.retryable,
                        "error": e.message[:200],
                    })
                    if streaming:
                        # Too late to fall back; surface the failure.
                        self.logger.error("mid-stream error from %s: %s", provider_name, e.message[:200])
                        self._record_usage(request_id, provider_name, mdef.id, key.id,
                                           key.masked, "error",
                                           (time.perf_counter() - t0) * 1000,
                                           0, 0, f"stream interrupted: {e.message}"[:200])
                        raise RoutingError(f"stream interrupted: {e.message}", attempts) from e
                    if e.status in (401, 403):
                        self.keystore.record_failure(key.id, f"auth failure ({e.status})",
                                                     cooldown_s=self.settings.key_cooldown_s)
                        continue
                    if not e.retryable:
                        self._record_usage(request_id, provider_name, mdef.id, key.id,
                                           key.masked, "error",
                                           (time.perf_counter() - t0) * 1000,
                                           0, 0, f"request failed: {e.message}"[:200])
                        raise RoutingError(f"request failed: {e.message}", attempts) from e
                    self.keystore.record_failure(key.id, e.message,
                                                 cooldown_s=self.settings.key_cooldown_s)
                    self._breaker_failure(provider_name)
                    continue
        # Pre-stream failure: nothing yielded yet. Record one error row with
        # the last provider actually attempted (may be "" if none was).
        last_provider = attempts[-1].get("provider", "") if attempts else ""
        self._record_usage(request_id, last_provider, model_id, "", "", "error",
                           (time.perf_counter() - overall_t0) * 1000,
                           0, 0, "all providers exhausted")
        raise RoutingError(
            f"failed to serve model '{model_id}': all providers/keys exhausted", attempts)
