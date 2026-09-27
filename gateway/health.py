"""Provider health checks + background health loop."""
from __future__ import annotations

import asyncio
import time


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


async def check_all(providers, keystore) -> dict:
    """Check every provider. Returns {name: {ok, latency_ms, detail, checked_at}}."""
    results: dict = {}
    for name, client in providers.items():
        api_key = None
        has_key = False
        try:
            key = keystore.pick(name)
            if key is not None:
                api_key = keystore.get_secret(key.id)
                has_key = True
        except Exception:
            api_key = None
        if not has_key:
            results[name] = {
                "ok": False,
                "latency_ms": 0.0,
                "detail": "no keys configured",
                "checked_at": _stamp(),
            }
            continue
        try:
            res = await client.health_check(api_key)
            results[name] = {
                "ok": bool(res.get("ok")),
                "latency_ms": round(float(res.get("latency_ms") or 0.0), 1),
                "detail": str(res.get("detail") or ("ok" if res.get("ok") else "check failed"))[:300],
                "checked_at": _stamp(),
            }
        except Exception as e:
            results[name] = {
                "ok": False,
                "latency_ms": 0.0,
                "detail": f"health check crashed: {e.__class__.__name__}",
                "checked_at": _stamp(),
            }
    return results


async def health_loop(providers, keystore, interval_s: float, callback) -> None:
    """Run check_all() every interval_s seconds, passing results to callback.

    callback may be a normal function or a coroutine function. Runs until the
    surrounding task is cancelled.
    """
    while True:
        try:
            results = await check_all(providers, keystore)
            out = callback(results)
            if asyncio.iscoroutine(out):
                await out
        except asyncio.CancelledError:
            raise
        except Exception:
            # health loop must never die on its own; Agent B logs via callback
            pass
        await asyncio.sleep(max(1.0, float(interval_s)))
