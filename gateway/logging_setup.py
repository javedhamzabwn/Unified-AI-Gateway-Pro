"""Structured logging with request_id correlation and secret scrubbing."""
from __future__ import annotations

import contextvars
import logging
import re

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# Redact things that look like secrets: sk-... tokens, Bearer tokens,
# api_key assignments. Deliberately conservative on Bearer (long tokens only).
_SCRUB_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9\-_]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/=]{16,}"),
    re.compile(r"(?i)(api[_-]?key\s*[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}]{6,})"),
]


def scrub(text: str) -> str:
    """Redact secret-looking values from a log string."""
    if not text:
        return text
    out = text
    for pat in _SCRUB_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) + "***REDACTED***") if m.lastindex else "***REDACTED***", out)
    return out


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        if isinstance(record.msg, str):
            record.msg = scrub(record.msg)
        if record.args:
            try:
                record.args = tuple(scrub(a) if isinstance(a, str) else a for a in record.args)
            except Exception:
                pass
        return True


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("uag")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
        handler.addFilter(_RequestIdFilter())
        logger.addHandler(handler)
    return logger


def set_request_id(rid: str) -> None:
    request_id_var.set(rid or "-")
