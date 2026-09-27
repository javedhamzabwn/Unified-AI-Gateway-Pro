"""Usage + cost tracking (SQLite). Costs are always labeled estimates."""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass


@dataclass
class UsageRecord:
    ts: float
    request_id: str
    provider: str
    model: str
    key_id: str
    key_masked: str
    status: str  # "ok" | "error"
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    error: str | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    request_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    key_id TEXT NOT NULL,
    key_masked TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_records(ts);
CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage_records(provider);
CREATE INDEX IF NOT EXISTS idx_usage_model ON usage_records(model);
"""


def estimate_cost(prompt_tokens: int, completion_tokens: int, model_def) -> float:
    """USD estimate from registry pricing (per 1k tokens). 0.0 pricing -> 0.0."""
    if model_def is None:
        return 0.0
    return (prompt_tokens / 1000.0) * float(model_def.input_price_per_1k or 0.0) + (
        completion_tokens / 1000.0
    ) * float(model_def.output_price_per_1k or 0.0)


class UsageStore:
    def __init__(self, db_path: str):
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def record(self, rec: UsageRecord) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO usage_records (ts, request_id, provider, model, key_id,"
                " key_masked, status, latency_ms, prompt_tokens, completion_tokens,"
                " cost_usd, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.ts, rec.request_id, rec.provider, rec.model, rec.key_id,
                    rec.key_masked, rec.status, rec.latency_ms, rec.prompt_tokens,
                    rec.completion_tokens, rec.cost_usd,
                    (rec.error or "")[:500] if rec.error else None,
                ),
            )

    def summary(self, days: int | None = None) -> dict:
        """Aggregates. days=None -> all time. Always includes cost_estimated=True."""
        where = ""
        params: tuple = ()
        if days is not None:
            where = "WHERE ts >= ?"
            params = (time.time() - days * 86400,)
        totals = self._conn.execute(
            f"SELECT COUNT(*) AS requests,"
            f" SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok_requests,"
            f" SUM(prompt_tokens) AS prompt_tokens,"
            f" SUM(completion_tokens) AS completion_tokens,"
            f" SUM(cost_usd) AS cost_usd,"
            f" AVG(latency_ms) AS avg_latency_ms"
            f" FROM usage_records {where}",
            params,
        ).fetchone()
        n_requests = totals["requests"] or 0
        n_ok = totals["ok_requests"] or 0
        n_errors = n_requests - n_ok
        by_provider = self._conn.execute(
            f"SELECT provider, COUNT(*) AS requests,"
            f" SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok_requests,"
            f" SUM(prompt_tokens + completion_tokens) AS tokens,"
            f" SUM(prompt_tokens) AS prompt_tokens,"
            f" SUM(completion_tokens) AS completion_tokens,"
            f" SUM(cost_usd) AS cost_usd, AVG(latency_ms) AS avg_latency_ms"
            f" FROM usage_records {where} GROUP BY provider ORDER BY requests DESC",
            params,
        ).fetchall()
        by_model = self._conn.execute(
            f"SELECT model, COUNT(*) AS requests,"
            f" SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok_requests,"
            f" SUM(prompt_tokens + completion_tokens) AS tokens,"
            f" SUM(prompt_tokens) AS prompt_tokens,"
            f" SUM(completion_tokens) AS completion_tokens,"
            f" SUM(cost_usd) AS cost_usd, AVG(latency_ms) AS avg_latency_ms"
            f" FROM usage_records {where} GROUP BY model ORDER BY requests DESC",
            params,
        ).fetchall()

        def _with_errors(rows):
            out = []
            for r in rows:
                d = dict(r)
                d["errors"] = (d.get("requests") or 0) - (d.get("ok_requests") or 0)
                out.append(d)
            return out

        return {
            "days": days,
            "totals": {
                "requests": n_requests,
                "ok_requests": n_ok,
                "error_requests": n_errors,
                "errors": n_errors,  # dashboard reads .errors
                "prompt_tokens": totals["prompt_tokens"] or 0,
                "completion_tokens": totals["completion_tokens"] or 0,
                "cost_usd": round(totals["cost_usd"] or 0.0, 6),
                "avg_latency_ms": round(totals["avg_latency_ms"] or 0.0, 1),
            },
            "by_provider": _with_errors(by_provider),
            "by_model": _with_errors(by_model),
            "cost_estimated": True,
        }

    def recent(self, limit: int = 100, status: str | None = None) -> list[dict]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM usage_records WHERE status = ?"
                " ORDER BY ts DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM usage_records ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
