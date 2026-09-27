"""Encrypted API key storage (Fernet + SQLite). BYOK: keys are owner-supplied."""
from __future__ import annotations

import os
import sqlite3
import stat
import time
import uuid
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


@dataclass
class KeyMeta:
    id: str
    provider: str
    label: str
    masked: str
    enabled: bool
    created_at: str | None
    last_used_at: str | None
    last_error: str | None
    consecutive_failures: int
    total_requests: int
    total_errors: int
    cooling_until: float = 0.0


def mask_secret(s: str) -> str:
    """Mask a secret for display/logs: keep a small prefix + last 4 chars."""
    if not s:
        return "••••"
    if len(s) <= 7:
        return "••••"
    return f"{s[:3]}••••••••{s[-4:]}"


def get_or_create_master_key(path: str) -> bytes:
    """Return the Fernet master key.

    Source: UAG_MASTER_KEY env var if set, else a 0600 file at ``path``
    (created on first use). Never log or print the key.
    """
    env_key = os.environ.get("UAG_MASTER_KEY")
    if env_key:
        key = env_key.strip().encode()
        Fernet(key)  # validates
        return key
    if os.path.exists(path):
        with open(path, "rb") as f:
            key = f.read().strip()
        Fernet(key)  # validates
        # enforce restrictive permissions even if the file predates us
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return key
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(key)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    # belt and braces: some platforms ignore the mode on os.open
    if stat.S_IMODE(os.stat(path).st_mode) != 0o600:
        os.chmod(path, 0o600)
    return key


_SCHEMA = """
CREATE TABLE IF NOT EXISTS keys (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    label TEXT NOT NULL,
    secret_enc TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    total_requests INTEGER NOT NULL DEFAULT 0,
    total_errors INTEGER NOT NULL DEFAULT 0,
    cooling_until REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_keys_provider ON keys(provider);
"""


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


class KeyStore:
    def __init__(self, db_path: str, master_key: bytes):
        self._fernet = Fernet(master_key)
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def _row_to_meta(self, row: sqlite3.Row) -> KeyMeta:
        return KeyMeta(
            id=row["id"],
            provider=row["provider"],
            label=row["label"],
            masked=mask_secret(self._fernet.decrypt(row["secret_enc"].encode()).decode()),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            last_error=row["last_error"],
            consecutive_failures=int(row["consecutive_failures"]),
            total_requests=int(row["total_requests"]),
            total_errors=int(row["total_errors"]),
            cooling_until=float(row["cooling_until"] or 0),
        )

    def add(self, provider: str, label: str, api_key: str) -> str:
        if not provider or not api_key:
            raise ValueError("provider and api_key are required")
        key_id = uuid.uuid4().hex[:16]
        secret_enc = self._fernet.encrypt(api_key.encode()).decode()
        with self._conn:
            self._conn.execute(
                "INSERT INTO keys (id, provider, label, secret_enc, enabled, created_at)"
                " VALUES (?, ?, ?, ?, 1, ?)",
                (key_id, provider, label or "", secret_enc, _now_iso()),
            )
        return key_id

    def list(self, provider: str | None = None) -> list[KeyMeta]:
        if provider:
            rows = self._conn.execute(
                "SELECT * FROM keys WHERE provider = ? ORDER BY provider, label", (provider,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM keys ORDER BY provider, label").fetchall()
        return [self._row_to_meta(r) for r in rows]

    def get(self, key_id: str) -> KeyMeta | None:
        row = self._conn.execute("SELECT * FROM keys WHERE id = ?", (key_id,)).fetchone()
        return self._row_to_meta(row) if row else None

    def get_secret(self, key_id: str) -> str:
        """Raw secret. Internal use only — never log, never return via API."""
        row = self._conn.execute("SELECT secret_enc FROM keys WHERE id = ?", (key_id,)).fetchone()
        if not row:
            raise KeyError(f"unknown key id: {key_id}")
        try:
            return self._fernet.decrypt(row["secret_enc"].encode()).decode()
        except InvalidToken as e:
            raise RuntimeError("keystore master key mismatch: cannot decrypt") from e

    def set_enabled(self, key_id: str, enabled: bool) -> bool:
        with self._conn:
            cur = self._conn.execute(
                "UPDATE keys SET enabled = ? WHERE id = ?", (1 if enabled else 0, key_id)
            )
        return cur.rowcount > 0

    def remove(self, key_id: str) -> bool:
        with self._conn:
            cur = self._conn.execute("DELETE FROM keys WHERE id = ?", (key_id,))
        return cur.rowcount > 0

    def record_success(self, key_id: str, latency_ms: float) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE keys SET last_used_at = ?, consecutive_failures = 0,"
                " last_error = NULL, cooling_until = 0,"
                " total_requests = total_requests + 1 WHERE id = ?",
                (_now_iso(), key_id),
            )

    def record_failure(self, key_id: str, error: str, cooldown_s: int = 60) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE keys SET last_used_at = ?,"
                " consecutive_failures = consecutive_failures + 1,"
                " last_error = ?, cooling_until = ?,"
                " total_requests = total_requests + 1,"
                " total_errors = total_errors + 1 WHERE id = ?",
                (_now_iso(), (error or "")[:500], time.time() + max(0, cooldown_s), key_id),
            )

    def pick(self, provider: str) -> KeyMeta | None:
        """Best usable key: enabled, not cooling, fewest failures, then oldest use."""
        now = time.time()
        row = self._conn.execute(
            "SELECT * FROM keys WHERE provider = ? AND enabled = 1 AND cooling_until <= ?"
            " ORDER BY consecutive_failures ASC, last_used_at ASC NULLS FIRST LIMIT 1",
            (provider, now),
        ).fetchone()
        return self._row_to_meta(row) if row else None

    def close(self) -> None:
        self._conn.close()
