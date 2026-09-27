"""Security tests: secret masking, file permissions, admin authz, no leakage."""
import json
import os
import stat

from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.keystore import get_or_create_master_key, mask_secret

AUTH = {"Authorization": "Bearer test-token"}


def test_mask_secret_never_leaks_prefix_or_middle():
    raw = "sk-super-secret-value-1234"
    masked = mask_secret(raw)
    assert raw not in masked
    assert "super-secret" not in masked
    assert masked.endswith("1234")


def test_master_key_file_is_0600(tmp_path):
    path = str(tmp_path / ".master_key")
    get_or_create_master_key(path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_master_key_reused_not_regenerated(tmp_path):
    path = str(tmp_path / ".master_key")
    first = get_or_create_master_key(path)
    second = get_or_create_master_key(path)
    assert first == second


def test_admin_api_disabled_without_token(test_settings):
    test_settings.admin_token = ""
    app = create_app(test_settings)
    with TestClient(app) as c:
        r = c.get("/admin/status")
        assert r.status_code == 401


def test_public_api_denied_without_auth_when_required(test_settings):
    test_settings.require_public_auth = True
    app = create_app(test_settings)
    with TestClient(app) as c:
        assert c.get("/v1/models").status_code == 401
        assert c.post("/v1/chat/completions",
                      json={"model": "m1",
                            "messages": [{"role": "user",
                                          "content": "hi"}]}).status_code == 401


def test_public_api_open_without_auth_by_default(test_settings):
    app = create_app(test_settings)
    with TestClient(app) as c:
        assert c.get("/v1/models").status_code == 200


def test_healthz_never_requires_auth(test_settings):
    test_settings.require_public_auth = True
    test_settings.admin_token = "x"
    app = create_app(test_settings)
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200


def test_key_listing_never_contains_raw_secret(test_settings):
    app = create_app(test_settings)
    raw = "sk-ultra-secret-9999"
    with TestClient(app) as c:
        r = c.post("/admin/keys", headers=AUTH,
                   json={"provider": "p1", "label": "s",
                         "api_key": raw})
        assert r.status_code == 200
        for _ in range(3):
            r = c.get("/admin/keys", headers=AUTH)
            assert raw not in json.dumps(r.json())
        r = c.get("/admin/status", headers=AUTH)
        assert raw not in json.dumps(r.json())
