"""Shared pytest fixtures for the Unified AI Gateway Pro test suite."""
import dataclasses
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gateway.config import ModelConfig, ProviderConfig, Settings


def _provider(name: str, **kw) -> ProviderConfig:
    base = dict(
        name=name,
        display_name=name.upper(),
        base_url="http://127.0.0.1:9",
        chat_path="/v1/chat/completions",
        models_path="/v1/models",
        api_style="openai",
        enabled=True,
        timeout_s=5.0,
        max_retries=0,
        priority=100,
    )
    base.update(kw)
    return ProviderConfig(**base)


@pytest.fixture
def tmp_data(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return str(d)


@pytest.fixture
def test_settings(tmp_data):
    return Settings(
        host="127.0.0.1",
        port=8008,
        data_dir=tmp_data,
        admin_token="test-token",
        require_public_auth=False,
        log_level="WARNING",
        cors_origins=[],
        circuit_breaker_threshold=2,
        circuit_breaker_cooldown_s=120,
        key_cooldown_s=30,
        providers=[_provider("p1"), _provider("p2")],
        models=[
            ModelConfig(id="m1", provider="p1", display_name="M1",
                        input_price_per_1k=1.0, output_price_per_1k=2.0,
                        fallbacks=["m2"]),
            ModelConfig(id="m2", provider="p2", display_name="M2",
                        input_price_per_1k=0.5, output_price_per_1k=1.0),
        ],
    )


@pytest.fixture
def no_cooldown_settings(test_settings):
    """Same settings but with zero key cooldown (lets one key be re-picked)."""
    return dataclasses.replace(test_settings, key_cooldown_s=0)


@pytest.fixture
def keystore(tmp_data):
    from gateway.keystore import KeyStore, get_or_create_master_key

    ks = KeyStore(
        os.path.join(tmp_data, "keys.db"),
        get_or_create_master_key(os.path.join(tmp_data, ".master_key")),
    )
    yield ks
    ks.close()


OK_CHAT_RESPONSE = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "m1",
    "choices": [{
        "index": 0,
        "message": {"role": "assistant", "content": "hello"},
        "finish_reason": "stop",
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5,
              "total_tokens": 15},
}

CHAT_PAYLOAD = {
    "model": "m1",
    "messages": [{"role": "user", "content": "hi"}],
}
