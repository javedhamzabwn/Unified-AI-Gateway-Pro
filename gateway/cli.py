#!/usr/bin/env python3
"""uag CLI: operate the Unified AI Gateway Pro from the terminal.

Usage:
    python -m gateway.cli <command> [options]

Commands:
    serve           run the gateway HTTP server (foreground)
    status          show gateway status (admin)
    providers       list providers with health + key counts (admin)
    models          list models (admin)
    keys list       list stored keys (masked, admin)
    keys add        add a key; the secret is read via getpass, never echoed
    keys enable     enable a key by id (admin)
    keys disable    disable a key by id (admin)
    keys remove     delete a key by id (admin)
    health          per-provider health snapshot (admin)
    usage           usage/cost summary (admin)
    config show     show sanitized local config (secrets blanked)
    logs            tail gateway.log via /admin/logs (admin)
    test            run the pytest suite

Exit codes: 0 success, 1 operational failure, 2 argparse usage error.
Never prints raw API secrets: the server never returns them.
"""
from __future__ import annotations

import argparse
import dataclasses
import getpass
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _die(message: str):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


from gateway.config import load_settings  # noqa: E402


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
def default_config_path() -> str:
    return os.environ.get(
        "UAG_CONFIG_PATH", os.path.join(REPO_ROOT, "config", "gateway.json")
    )


def _settings(args):
    return load_settings(config_path=args.config)


def _base_url(args, settings) -> str:
    host = getattr(args, "host", None) or settings.host
    port = getattr(args, "port", None) or settings.port
    return f"http://{host}:{port}"


def _token(args) -> str:
    return (
        getattr(args, "token", None)
        or os.environ.get("UAG_ADMIN_TOKEN", "")
        or ""
    ).strip()


def _http():
    try:
        import httpx
    except ImportError:
        _die("httpx is required for remote commands (pip install httpx)")
    return httpx


def _request(method: str, url: str, token: str, timeout: float = 15.0, **kwargs):
    httpx = _http()
    headers = dict(kwargs.pop("headers", {}) or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            return client.request(method, url, headers=headers, **kwargs)
    except httpx.ConnectError:
        _die(f"cannot reach gateway at {url} (is it running? try 'uag serve')")
    except httpx.TimeoutException:
        _die(f"request to {url} timed out after {timeout}s")


def _admin_get(args, path: str, params: dict | None = None):
    settings = _settings(args)
    url = _base_url(args, settings) + path
    r = _request("GET", url, _token(args), params=params)
    if r.status_code == 401:
        _die("unauthorized: bad or missing admin token (--token or UAG_ADMIN_TOKEN)")
    if r.status_code >= 400:
        _die(f"{path} failed: HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def _table(rows: list[list], headers: list[str]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join("{:<%d}" % w for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


def _add_remote(parser: argparse.ArgumentParser, *, token: bool = True) -> None:
    # SUPPRESS defaults: a value given at the top level must survive
    parser.add_argument("--host", default=argparse.SUPPRESS,
                        help="gateway host (default: from config)")
    parser.add_argument("--port", type=int, default=argparse.SUPPRESS,
                        help="gateway port (default: from config)")
    if token:
        parser.add_argument("--token", default=argparse.SUPPRESS,
                            help="admin token (default: UAG_ADMIN_TOKEN)")


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_serve(args) -> int:
    settings = _settings(args)
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    try:
        import uvicorn
    except ImportError:
        _die("uvicorn is required to serve (pip install uvicorn)")
    from gateway.app import create_app

    print(f"starting gateway on http://{settings.host}:{settings.port} "
          f"(data: {settings.data_dir})")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                log_level=settings.log_level.lower())
    return 0


def cmd_status(args) -> int:
    s = _admin_get(args, "/admin/status")
    print(f"status:      {s.get('status')}")
    print(f"version:     {s.get('version')}")
    print(f"uptime:      {s.get('uptime_s')}s   pid: {s.get('pid')}")
    print(f"providers:   {s.get('providers_enabled')}/{s.get('providers_total')} enabled")
    print(f"keys:        {s.get('keys_total')}")
    print(f"models:      {s.get('models_enabled')}/{s.get('models_total')} enabled")
    print(f"data dir:    {s.get('data_dir')}")
    return 0


def cmd_providers(args) -> int:
    data = _admin_get(args, "/admin/providers")
    rows = []
    for p in data.get("providers", []):
        health = p.get("health") or {}
        if health.get("ok"):
            hs = f"ok {health.get('latency_ms', '?')}ms"
        elif health:
            hs = f"down: {str(health.get('detail'))[:40]}"
        else:
            hs = "unknown"
        rows.append([p.get("name"), p.get("display_name"),
                     "yes" if p.get("enabled") else "no",
                     p.get("key_count"), p.get("model_count"), hs])
    _table(rows, ["name", "display name", "enabled", "keys", "models", "health"])
    return 0


def cmd_models(args) -> int:
    data = _admin_get(args, "/admin/models")
    rows = []
    for m in data.get("models", []):
        rows.append([m.get("id"), m.get("provider"),
                     "yes" if m.get("enabled") else "no",
                     m.get("priority"), ",".join(m.get("fallbacks") or [])])
    _table(rows, ["id", "provider", "enabled", "priority", "fallbacks"])
    return 0


def cmd_keys_list(args) -> int:
    params = {"provider": args.provider} if args.provider else None
    data = _admin_get(args, "/admin/keys", params=params)
    rows = []
    for k in data.get("keys", []):
        rows.append([k.get("id"), k.get("provider"), k.get("label"),
                     k.get("masked"), "yes" if k.get("enabled") else "no",
                     k.get("consecutive_failures"), k.get("total_requests")])
    _table(rows, ["id", "provider", "label", "masked",
                  "enabled", "failures", "requests"])
    return 0


def cmd_keys_add(args) -> int:
    secret = getpass.getpass("API key (hidden, will not echo): ").strip()
    if len(secret) < 8:
        _die("API key must be at least 8 characters")
    settings = _settings(args)
    url = _base_url(args, settings) + "/admin/keys"
    r = _request("POST", url, _token(args),
                 json={"provider": args.provider, "label": args.label,
                       "api_key": secret})
    if r.status_code == 401:
        _die("unauthorized: bad or missing admin token (--token or UAG_ADMIN_TOKEN)")
    if r.status_code >= 400:
        _die(f"add key failed: HTTP {r.status_code}: {r.text[:300]}")
    key = r.json().get("key", {})
    # the server never returns the secret; still, never print the payload raw
    print(f"added key {key.get('id')} ({key.get('masked')})")
    return 0


def _keys_patch(args, enabled: bool | None, delete: bool = False) -> int:
    settings = _settings(args)
    base = _base_url(args, settings) + f"/admin/keys/{args.id}"
    if delete:
        r = _request("DELETE", base, _token(args))
    else:
        r = _request("PATCH", base, _token(args), json={"enabled": enabled})
    if r.status_code == 401:
        _die("unauthorized: bad or missing admin token (--token or UAG_ADMIN_TOKEN)")
    if r.status_code == 404:
        _die(f"key '{args.id}' not found")
    if r.status_code >= 400:
        _die(f"request failed: HTTP {r.status_code}: {r.text[:300]}")
    if delete:
        print(f"deleted key {args.id}")
    else:
        k = r.json().get("key", {})
        print(f"key {k.get('id')} enabled={k.get('enabled')}")
    return 0


def cmd_health(args) -> int:
    data = _admin_get(args, "/admin/health")
    rows = []
    for name, h in (data.get("providers") or {}).items():
        rows.append([name, "ok" if h.get("ok") else "down",
                     h.get("latency_ms"), str(h.get("detail"))[:60]])
    _table(rows, ["provider", "status", "latency_ms", "detail"])
    return 0


def cmd_usage(args) -> int:
    data = _admin_get(args, "/admin/usage", params={"days": str(args.days)})
    t = data.get("totals", {})
    prompt = t.get("prompt_tokens", 0) or 0
    completion = t.get("completion_tokens", 0) or 0
    print(f"requests:    {t.get('requests')} "
          f"(ok {t.get('ok_requests')}, errors {t.get('error_requests')})")
    print(f"tokens:      in {prompt}, out {completion}, "
          f"total {prompt + completion}")
    print(f"cost (est):  ${t.get('cost_usd', 0):.4f}")
    print(f"avg latency: {t.get('avg_latency_ms')}ms")
    print("\nby provider:")
    rows = []
    for p in data.get("by_provider", []):
        reqs = p.get("requests") or 0
        ok = p.get("ok_requests") or 0
        rows.append([p.get("provider"), reqs, ok, reqs - ok,
                     p.get("tokens"), f"${p.get('cost_usd', 0):.4f}"])
    _table(rows, ["provider", "requests", "ok", "errors", "tokens", "cost"])
    print("\nby model:")
    rows = []
    for m in data.get("by_model", []):
        reqs = m.get("requests") or 0
        ok = m.get("ok_requests") or 0
        rows.append([m.get("model"), m.get("provider"), reqs, ok,
                     m.get("tokens"), f"${m.get('cost_usd', 0):.4f}"])
    _table(rows, ["model", "provider", "requests", "ok", "tokens", "cost"])
    return 0


def cmd_config_show(args) -> int:
    token = _token(args)
    if token:
        # live view from the running gateway
        data = _admin_get(args, "/admin/config")
        print(json.dumps(data.get("config"), indent=2))
        return 0
    settings = _settings(args)
    d = dataclasses.asdict(settings)
    d["admin_token"] = None
    d["admin_token_configured"] = bool(settings.admin_token)
    print(json.dumps(d, indent=2))
    return 0


def cmd_logs(args) -> int:
    data = _admin_get(args, "/admin/logs", params={"lines": str(args.lines)})
    for line in data.get("lines", []):
        print(line)
    return 0


def cmd_test(args) -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        cwd=REPO_ROOT,
    )
    return proc.returncode


# --------------------------------------------------------------------------- #
# argparse wiring
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="uag", description="Unified AI Gateway Pro CLI")
    p.add_argument("--config", default=None,
                   help="config file path (default: config/gateway.json)")
    # global connection flags (also accepted per-subcommand); SUPPRESS so
    # subcommand defaults do not clobber values given here
    p.add_argument("--host", default=argparse.SUPPRESS,
                   help="gateway host (default: from config)")
    p.add_argument("--port", type=int, default=argparse.SUPPRESS,
                   help="gateway port (default: from config)")
    p.add_argument("--token", default=argparse.SUPPRESS,
                   help="admin token (default: UAG_ADMIN_TOKEN)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="run the gateway HTTP server")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    # SUPPRESS so a top-level --config is not clobbered by this default
    s.add_argument("--config", default=argparse.SUPPRESS,
                   help="config file path (default: config/gateway.json)")
    s.set_defaults(func=cmd_serve)

    for name, help_text, func in [
        ("status", "show gateway status", cmd_status),
        ("providers", "list providers with health", cmd_providers),
        ("models", "list models", cmd_models),
        ("health", "per-provider health snapshot", cmd_health),
        ("logs", "tail gateway.log", cmd_logs),
    ]:
        c = sub.add_parser(name, help=help_text)
        _add_remote(c)
        if name == "logs":
            c.add_argument("--lines", type=int, default=200)
        c.set_defaults(func=func)

    k = sub.add_parser("keys", help="manage provider API keys")
    ks = k.add_subparsers(dest="keys_command", required=True)

    kl = ks.add_parser("list", help="list keys (masked)")
    kl.add_argument("--provider", default=None)
    _add_remote(kl)
    kl.set_defaults(func=cmd_keys_list)

    ka = ks.add_parser("add", help="add a key (secret read hidden via getpass)")
    ka.add_argument("--provider", required=True)
    ka.add_argument("--label", required=True)
    _add_remote(ka)
    ka.set_defaults(func=cmd_keys_add)

    for cname, chelp in [("enable", "enable a key"), ("disable", "disable a key"),
                         ("remove", "delete a key")]:
        kc = ks.add_parser(cname, help=chelp)
        kc.add_argument("--id", required=True)
        _add_remote(kc)
        if cname == "remove":
            kc.set_defaults(func=lambda a: _keys_patch(a, None, delete=True))
        else:
            kc.set_defaults(
                func=lambda a, e=(cname == "enable"): _keys_patch(a, e))
    u = sub.add_parser("usage", help="usage/cost summary")
    u.add_argument("--days", type=int, default=30)
    _add_remote(u)
    u.set_defaults(func=cmd_usage)

    cs = sub.add_parser("config", help="config helpers")
    css = cs.add_subparsers(dest="config_command", required=True)
    cshow = css.add_parser("show", help="show sanitized config")
    _add_remote(cshow)
    cshow.set_defaults(func=cmd_config_show)

    t = sub.add_parser("test", help="run the pytest suite")
    t.set_defaults(func=cmd_test)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "config", None) is None:
        args.config = default_config_path()
    try:
        return args.func(args) or 0
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
