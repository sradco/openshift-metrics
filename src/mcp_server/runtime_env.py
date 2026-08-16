"""Load MCP / Telemeter env files once (exported values win)."""

from __future__ import annotations

import os
from pathlib import Path

# Restored after files load so an exported value beats .env and XDG.
_EXPORT_WINS = (
    "PROM_URL",
    "CLIENTID",
    "CLIENTSECRET",
    "MCP_HTTP_TOKEN",
    "MCP_HOST",
    "MCP_PORT",
    "MCP_PATH",
    "MCP_TRANSPORT",
)

_loaded = False


def reset_runtime_env_for_tests() -> None:
    """Allow tests to reload files (not used at runtime)."""
    global _loaded
    _loaded = False


def _xdg_env_path() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    base = Path(raw) if raw else Path.home() / ".config"
    return base / "openshift-metrics" / "env"


def load_runtime_env(repo_root: Path) -> None:
    """Load XDG env, then repo .env. Non-empty exported keys always win.

    No-op if python-dotenv is missing or this process already loaded files.
    """
    global _loaded
    if _loaded:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _loaded = True
        return

    saved = {key: os.environ[key] for key in _EXPORT_WINS if os.environ.get(key)}
    load_dotenv(_xdg_env_path(), override=True)
    load_dotenv(Path(repo_root) / ".env", override=True)
    os.environ.update(saved)
    _loaded = True
