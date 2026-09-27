# Quarantined legacy components

These files are the original experimental components of this repository, moved
out of the serving path on 2026-09-26 during the BYOK gateway rebuild.

## What is here

- `kilo_mailtm.py`, `ainative_mailtm.py` — experimental browser automation that
  created accounts via throwaway email services to generate API keys. This is
  account-creation automation / signup-flow bypass tooling. It is **not** part
  of the gateway, is not imported by anything, and must not be reintroduced
  into the serving path.
- `browser_manager.py` — stealth browser driver factory (undetected-chromedriver,
  anti-detect flags) that existed to support the above. Not used by the gateway.
- `kilo_proxy.py` — the original proxy. Replaced by the `gateway/` package. Kept
  for reference only; it served keys from plaintext `kilo_keys.txt` /
  `ainative_keys.txt` files and had no authentication.
- `dashboard.html` — original dashboard, tied to the old proxy endpoints.
- `list_models.py`, `test_proxy.py` — old utilities.
- `Install.bat`, `install.ps1`, `api_cli.ps1`, `run.bat`, `start_all.ps1`,
  `stop_all.ps1`, `restore_personal_chrome.ps1` — old Windows-only control scripts,
  replaced by the cross-platform Python CLI (`gateway/cli.py`).

## Rules

1. Nothing in `gateway/`, `tests/`, or the CLI may import from this directory.
2. Do not "fix" or extend the harvesting automation. It stays frozen.
3. If any file here is ever needed for legitimate research, copy it out
   explicitly and document why — do not wire it back into the gateway.

Git history is preserved (`git log --follow`) for audit purposes.
