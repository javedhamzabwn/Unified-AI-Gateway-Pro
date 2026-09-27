"""KeyStore tests: masking, secret round-trip, selection rules, failure accounting."""
import dataclasses
import json

import pytest

from gateway.keystore import mask_secret


def _add(ks, provider, label, secret):
    return ks.add(provider, label, secret)


def test_add_and_list_masks_secret(keystore):
    raw = "sk-live-abc123XYZ9999"
    kid = _add(keystore, "p1", "main", raw)
    metas = keystore.list("p1")
    assert len(metas) == 1
    meta = metas[0]
    assert meta.id == kid
    assert meta.provider == "p1"
    assert meta.label == "main"
    # raw secret must not appear anywhere in the metadata
    assert raw not in meta.masked
    blob = json.dumps([dataclasses.asdict(m) for m in metas])
    assert raw not in blob
    assert "sk-live" not in blob


def test_mask_secret_format():
    m = mask_secret("sk-live-abc123XYZ9999")
    assert m.endswith("9999")
    assert m.startswith("sk-")
    assert "abc123XYZ" not in m


def test_mask_secret_short_values():
    # short secrets reveal nothing at all
    assert mask_secret("") == "••••"
    assert mask_secret("x") == "••••"
    assert mask_secret("1234567") == "••••"


def test_secret_round_trip(keystore):
    raw = "sk-roundtrip-456-def"
    kid = _add(keystore, "p1", "rt", raw)
    assert keystore.get_secret(kid) == raw


def test_pick_skips_disabled_key(keystore):
    k1 = _add(keystore, "p1", "a", "sk-aaa-11111111")
    k2 = _add(keystore, "p1", "b", "sk-bbb-22222222")
    keystore.set_enabled(k1, False)
    picked = keystore.pick("p1")
    assert picked is not None
    assert picked.id == k2


def test_pick_skips_cooling_key(keystore):
    k1 = _add(keystore, "p1", "a", "sk-aaa-11111111")
    k2 = _add(keystore, "p1", "b", "sk-bbb-22222222")
    keystore.set_enabled(k1, False)
    keystore.record_failure(k2, "boom", cooldown_s=600)
    assert keystore.pick("p1") is None


def test_pick_prefers_fewest_failures(keystore):
    k1 = _add(keystore, "p1", "a", "sk-aaa-11111111")
    k2 = _add(keystore, "p1", "b", "sk-bbb-22222222")
    keystore.record_failure(k1, "err", cooldown_s=0)
    picked = keystore.pick("p1")
    assert picked is not None
    assert picked.id == k2


def test_failure_and_success_accounting(keystore):
    k1 = _add(keystore, "p1", "a", "sk-aaa-11111111")
    keystore.record_failure(k1, "e1", cooldown_s=0)
    keystore.record_failure(k1, "e2", cooldown_s=0)
    meta = keystore.get(k1)
    assert meta.consecutive_failures == 2
    assert meta.total_errors == 2
    assert meta.last_error == "e2"
    keystore.record_success(k1, 12.5)
    meta = keystore.get(k1)
    assert meta.consecutive_failures == 0
    # total_requests counts every attempt (2 failures + 1 success)
    assert meta.total_requests == 3
    assert meta.last_error is None  # a success clears the last error


def test_remove_clears_secret(keystore):
    raw = "sk-first-11111111"
    kid = _add(keystore, "p1", "a", raw)
    assert keystore.remove(kid) is True
    assert keystore.get(kid) is None
    with pytest.raises(KeyError):
        keystore.get_secret(kid)
    # removing twice is a clean no-op
    assert keystore.remove(kid) is False
    # re-adding works after removal
    kid2 = _add(keystore, "p1", "a", "sk-second-22222222")
    assert keystore.get_secret(kid2) == "sk-second-22222222"


def test_unknown_provider_pick_returns_none(keystore):
    assert keystore.pick("nope") is None
