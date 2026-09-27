"""Provider abstraction: OpenAI-compatible HTTP clients over httpx."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import AsyncIterator

import httpx


@dataclass
class ProviderDef:
    name: str
    base_url: str
    chat_path: str
    models_path: str
    enabled: bool
    priority: int
    timeout_s: float
    max_retries: int


class ProviderError(Exception):
    def __init__(self, status: int | None, message: str, retryable: bool):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retryable = retryable


def _classify_status(status: int, body_snippet: str) -> ProviderError:
    """Map HTTP status to retryability. Never include secrets in messages."""
    if status == 429:
        return ProviderError(status, f"rate limited (429): {body_snippet}", True)
    if status == 401:
        return ProviderError(status, f"unauthorized (401): key invalid or revoked: {body_snippet}", False)
    if status == 403:
        return ProviderError(status, f"forbidden (403): {body_snippet}", False)
    if status == 400:
        return ProviderError(status, f"bad request (400): {body_snippet}", False)
    if status == 404:
        return ProviderError(status, f"not found (404): {body_snippet}", False)
    if 500 <= status <= 599:
        return ProviderError(status, f"provider error ({status}): {body_snippet}", True)
    return ProviderError(status, f"unexpected status ({status}): {body_snippet}", False)


class ProviderClient:
    def __init__(self, definition: ProviderDef):
        self.definition = definition
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # trust_env=False: never inherit ambient proxy env vars (e.g. a
            # malformed HTTPS_PROXY in the host environment must not break
            # provider calls). Proxy policy belongs to gateway config, not env.
            self._client = httpx.AsyncClient(
                base_url=self.definition.base_url,
                timeout=httpx.Timeout(self.definition.timeout_s),
                headers={"Content-Type": "application/json"},
                trust_env=False,
            )
        return self._client

    @staticmethod
    def _headers(api_key: str) -> dict:
        # api_key is only ever placed in the Authorization header, never logged.
        return {"Authorization": f"Bearer {api_key}"}

    async def chat(self, model: str, payload: dict, api_key: str, request_id: str) -> dict:
        body = dict(payload)
        body["model"] = model
        body.pop("stream", None)
        try:
            client = self._get_client()
            resp = await client.post(
                self.definition.chat_path, json=body, headers=self._headers(api_key)
            )
        except httpx.TimeoutException:
            raise ProviderError(None, f"timeout after {self.definition.timeout_s}s", True)
        except httpx.ConnectError as e:
            raise ProviderError(None, f"connection failed: {e}", True)
        except httpx.HTTPError as e:
            raise ProviderError(None, f"http error: {e}", True)
        except Exception as e:
            # Client construction / unexpected transport failure: treat as
            # retryable so the router can fall back instead of 500ing.
            raise ProviderError(None, f"transport error: {e.__class__.__name__}", True)
        if resp.status_code != 200:
            raise _classify_status(resp.status_code, resp.text[:300])
        try:
            return resp.json()
        except ValueError as e:
            raise ProviderError(resp.status_code, f"malformed JSON response: {e}", True)

    async def chat_stream(
        self, model: str, payload: dict, api_key: str, request_id: str
    ) -> AsyncIterator[bytes]:
        body = dict(payload)
        body["model"] = model
        body["stream"] = True
        try:
            client = self._get_client()
            async with client.stream(
                "POST", self.definition.chat_path, json=body, headers=self._headers(api_key)
            ) as resp:
                if resp.status_code != 200:
                    text = (await resp.aread()).decode("utf-8", "replace")
                    raise _classify_status(resp.status_code, text[:300])
                async for chunk in resp.aiter_bytes():
                    yield chunk
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError(None, f"stream timeout after {self.definition.timeout_s}s", True)
        except httpx.ConnectError as e:
            raise ProviderError(None, f"stream connection failed: {e}", True)
        except httpx.HTTPError as e:
            raise ProviderError(None, f"stream http error: {e}", True)
        except Exception as e:
            raise ProviderError(None, f"stream transport error: {e.__class__.__name__}", True)

    async def health_check(self, api_key: str | None = None) -> dict:
        """GET the models endpoint (or base URL). Returns ok/latency_ms/detail."""
        t0 = time.perf_counter()
        headers = self._headers(api_key) if api_key else {}
        try:
            resp = await self._get_client().get(self.definition.models_path, headers=headers)
            latency_ms = (time.perf_counter() - t0) * 1000
            ok = resp.status_code < 400
            return {
                "ok": ok,
                "latency_ms": round(latency_ms, 1),
                "detail": f"HTTP {resp.status_code}" if not ok else "ok",
            }
        except httpx.TimeoutException:
            return {"ok": False, "latency_ms": (time.perf_counter() - t0) * 1000,
                    "detail": "timeout"}
        except httpx.HTTPError as e:
            return {"ok": False, "latency_ms": (time.perf_counter() - t0) * 1000,
                    "detail": f"connection failed: {e.__class__.__name__}"}

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def build_providers(settings) -> dict[str, ProviderClient]:
    """Build runtime provider clients from Settings (sorted by priority)."""
    defs: dict[str, ProviderClient] = {}
    for pcfg in sorted(settings.providers, key=lambda p: (p.priority, p.name)):
        if not pcfg.enabled:
            continue
        definition = ProviderDef(
            name=pcfg.name,
            base_url=pcfg.base_url.rstrip("/"),
            chat_path=pcfg.chat_path,
            models_path=pcfg.models_path,
            enabled=pcfg.enabled,
            priority=pcfg.priority,
            timeout_s=pcfg.timeout_s,
            max_retries=pcfg.max_retries,
        )
        defs[pcfg.name] = ProviderClient(definition)
    return defs
