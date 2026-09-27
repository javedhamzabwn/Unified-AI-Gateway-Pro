"""Usage store tests: summary arithmetic and cost estimation."""
import os
import time

from gateway.registry import ModelDef
from gateway.usage import UsageRecord, UsageStore, estimate_cost


def _store(tmp_path):
    return UsageStore(str(tmp_path / "usage.db"))


def _rec(**kw):
    base = dict(ts=time.time(), request_id="r", provider="p1", model="m1",
                key_id="k1", key_masked="sk-***1111", status="ok",
                latency_ms=100.0, prompt_tokens=0, completion_tokens=0,
                cost_usd=0.0)
    base.update(kw)
    return UsageRecord(**base)


def test_summary_arithmetic(tmp_path):
    store = _store(tmp_path)
    now = time.time()
    store.record(_rec(request_id="r1", ts=now, prompt_tokens=1000,
                      completion_tokens=500, cost_usd=2.0,
                      latency_ms=100.0))
    store.record(_rec(request_id="r2", ts=now, status="error",
                      latency_ms=50.0, error="boom"))

    s = store.summary()
    assert s["cost_estimated"] is True
    t = s["totals"]
    assert t["requests"] == 2
    assert t["ok_requests"] == 1
    assert t["error_requests"] == 1
    assert t["prompt_tokens"] == 1000
    assert t["completion_tokens"] == 500
    assert t["cost_usd"] == 2.0
    assert t["avg_latency_ms"] == 75.0

    prov = s["by_provider"]
    assert len(prov) == 1
    assert prov[0]["provider"] == "p1"
    assert prov[0]["requests"] == 2
    assert prov[0]["tokens"] == 1500

    models = s["by_model"]
    assert len(models) == 1
    assert models[0]["model"] == "m1"
    assert models[0]["cost_usd"] == 2.0


def test_summary_days_filter(tmp_path):
    store = _store(tmp_path)
    store.record(_rec(request_id="old", ts=time.time() - 30 * 86400))
    store.record(_rec(request_id="new", ts=time.time()))
    assert store.summary(days=7)["totals"]["requests"] == 1
    assert store.summary()["totals"]["requests"] == 2


def test_recent_listing(tmp_path):
    store = _store(tmp_path)
    store.record(_rec(request_id="r1"))
    store.record(_rec(request_id="r2", status="error", error="x"))
    rows = store.recent(limit=10)
    assert len(rows) == 2
    rows = store.recent(limit=10, status="error")
    assert len(rows) == 1
    assert rows[0]["request_id"] == "r2"


def test_estimate_cost_with_model():
    m = ModelDef(id="m", provider="p", input_price_per_1k=1.0,
                 output_price_per_1k=2.0)
    assert estimate_cost(1000, 500, m) == 2.0
    assert estimate_cost(0, 0, m) == 0.0


def test_estimate_cost_without_model():
    assert estimate_cost(100, 100, None) == 0.0


def test_estimate_cost_missing_prices():
    m = ModelDef(id="m", provider="p")
    assert estimate_cost(1000, 1000, m) == 0.0


def test_summary_includes_errors_field(tmp_path):
    """Regression: the dashboard reads .errors, so summary() must provide
    it on totals and on by_provider/by_model rows."""
    store = _store(tmp_path)
    now = time.time()
    store.record(_rec(request_id="r1", ts=now))
    store.record(_rec(request_id="r2", ts=now, status="error", error="boom"))

    s = store.summary()
    assert s["totals"]["errors"] == 1
    assert s["totals"]["error_requests"] == 1  # legacy alias kept
    assert s["by_provider"][0]["errors"] == 1
    assert s["by_model"][0]["errors"] == 1


def test_by_model_groups_by_model_only(tmp_path):
    """Regression: the dashboard 'By model' table shows one row per model.
    Grouping by (model, provider) produced duplicate-looking rows for the
    same model served via different providers."""
    store = _store(tmp_path)
    now = time.time()
    store.record(_rec(request_id="r1", ts=now, model="m1", provider="p1"))
    store.record(_rec(request_id="r2", ts=now, model="m1", provider="p2",
                      status="error", error="boom"))
    s = store.summary()
    assert len(s["by_model"]) == 1
    row = s["by_model"][0]
    assert row["model"] == "m1"
    assert row["requests"] == 2
    assert row["errors"] == 1
    # provider breakdown still splits correctly
    assert len(s["by_provider"]) == 2


def test_grouped_rows_include_token_splits(tmp_path):
    """Regression: the dashboard renders per-row prompt/completion tokens,
    so by_provider/by_model rows must carry the split fields, not just
    the combined 'tokens'."""
    store = _store(tmp_path)
    now = time.time()
    store.record(_rec(request_id="r1", ts=now, prompt_tokens=100,
                      completion_tokens=50))
    s = store.summary()
    assert s["by_provider"][0]["prompt_tokens"] == 100
    assert s["by_provider"][0]["completion_tokens"] == 50
    assert s["by_model"][0]["prompt_tokens"] == 100
    assert s["by_model"][0]["completion_tokens"] == 50
