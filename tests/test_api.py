"""API tests: health, model listing, chat (mocked router), admin auth, key masking."""
import json

import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def app(test_settings):
    return create_app(test_settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


class _FakeRouter:
    async def complete(self, payload, request_id):
        return {
            "id": "chatcmpl-x",
            "object": "chat.completion",
            "model": payload.get("model"),
            "choices": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "total_tokens": 2},
        }

    async def complete_stream(self, payload, request_id):
        yield b'data: {"delta": "hi"}\n\n'


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert "X-Request-ID" in r.headers


def test_models_list_enabled_only(client):
    r = client.get("/v1/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["data"]]
    assert "m1" in ids
    assert "m2" in ids


def test_chat_completions_mocked_router(app):
    app.state.router = _FakeRouter()
    with TestClient(app) as c:
        r = c.post("/v1/chat/completions",
                   json={"model": "m1",
                         "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert r.json()["id"] == "chatcmpl-x"
    assert "X-Request-ID" in r.headers


def test_chat_stream_mocked_router(app):
    app.state.router = _FakeRouter()
    with TestClient(app) as c:
        r = c.post("/v1/chat/completions",
                   json={"model": "m1", "stream": True,
                         "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert "[DONE]" in r.text


def test_chat_unknown_model_404(client):
    r = client.post("/v1/chat/completions",
                    json={"model": "nope",
                          "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 404


def test_chat_missing_model_400(client):
    r = client.post("/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 400


def test_admin_endpoints_require_token(client):
    for path in ["/admin/status", "/admin/providers", "/admin/models",
                 "/admin/keys", "/admin/usage", "/admin/health",
                 "/admin/logs", "/admin/config"]:
        r = client.get(path)
        assert r.status_code == 401, path


def test_admin_wrong_token_rejected(client):
    r = client.get("/admin/status",
                   headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_admin_status_ok(client):
    r = client.get("/admin/status", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert body["models_total"] == 2


def test_admin_key_add_never_returns_secret(client):
    raw = "sk-admin-test-secret-7890"
    r = client.post("/admin/keys", headers=AUTH,
                    json={"provider": "p1", "label": "t", "api_key": raw})
    assert r.status_code == 200
    body = r.json()
    assert raw not in json.dumps(body)
    assert body["key"]["masked"].endswith("7890")
    key_id = body["key"]["id"]

    r = client.get("/admin/keys", headers=AUTH)
    assert r.status_code == 200
    assert raw not in json.dumps(r.json())

    r = client.patch(f"/admin/keys/{key_id}", headers=AUTH,
                     json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["key"]["enabled"] is False

    r = client.delete(f"/admin/keys/{key_id}", headers=AUTH)
    assert r.status_code == 200


def test_admin_config_masks_token(client):
    r = client.get("/admin/config", headers=AUTH)
    assert r.status_code == 200
    cfg = r.json()["config"]
    assert cfg["admin_token"] is None
    assert cfg["admin_token_configured"] is True
    assert "test-token" not in json.dumps(r.json())


def test_startup_does_not_block_on_health_checks(app, monkeypatch):
    """Regression: the lifespan must not await provider network I/O before
    the server accepts traffic. A hanging check_all must not delay startup."""
    import asyncio
    import time

    import gateway.health as health_module

    async def _hanging_check_all(providers, keystore):
        await asyncio.sleep(30)
        return {}

    monkeypatch.setattr(health_module, "check_all", _hanging_check_all)
    t0 = time.perf_counter()
    with TestClient(app) as c:
        r = c.get("/healthz")
        elapsed = time.perf_counter() - t0
    assert r.status_code == 200
    assert elapsed < 10, f"startup blocked on health check ({elapsed:.1f}s)"
