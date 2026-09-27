"""Config tests: defaults, env overrides, invalid provider URLs."""
import json
import os

import pytest

from gateway.config import load_settings

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_defaults_with_missing_file(tmp_path):
    s = load_settings(config_path=str(tmp_path / "does-not-exist.json"))
    assert s.host == "127.0.0.1"
    assert s.port == 8008
    assert s.data_dir == "data"
    assert s.admin_token == ""
    assert s.require_public_auth is False


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("UAG_PORT", "9001")
    monkeypatch.setenv("UAG_HOST", "0.0.0.0")
    monkeypatch.setenv("UAG_ADMIN_TOKEN", "sekret")
    s = load_settings(config_path=str(tmp_path / "does-not-exist.json"))
    assert s.port == 9001
    assert s.host == "0.0.0.0"
    assert s.admin_token == "sekret"


def test_invalid_provider_url_rejected(tmp_path):
    cfg = {
        "providers": [{
            "name": "bad",
            "display_name": "Bad",
            "base_url": "ftp://example.com/x",
            "chat_path": "/v1/chat",
            "models_path": "/v1/models",
        }],
        "models": [],
    }
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        load_settings(config_path=str(p))


def test_valid_config_loads(tmp_path):
    cfg = {
        "port": 8123,
        "providers": [{
            "name": "p1",
            "display_name": "P1",
            "base_url": "https://api.example.com",
            "chat_path": "/v1/chat",
            "models_path": "/v1/models",
        }],
        "models": [{
            "id": "m1",
            "provider": "p1",
            "display_name": "M1",
            "fallbacks": ["m2"],
        }],
    }
    p = tmp_path / "good.json"
    p.write_text(json.dumps(cfg))
    s = load_settings(config_path=str(p))
    assert s.port == 8123
    assert s.providers[0].name == "p1"
    assert s.models[0].fallbacks == ["m2"]


def test_repo_default_config_loads():
    s = load_settings(
        config_path=os.path.join(REPO_ROOT, "config", "gateway.json"))
    names = {p.name for p in s.providers}
    assert "kilo" in names
    assert len(s.models) >= 1
