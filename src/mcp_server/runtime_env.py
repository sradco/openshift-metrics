"""Load MCP / Telemeter env files once (exported values win)."""

from __future__ import annotations

import os
import sys
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

    No-op if this process already loaded files. Raises ImportError if
    python-dotenv is missing (do not start without loading credentials).
    """
    global _loaded
    if _loaded:
        return
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        print(
            "openshift-metrics: python-dotenv is required to load .env. "
            "From a terminal: ./scripts/install_mcp.sh",
            file=sys.stderr,
        )
        raise ImportError(
            "python-dotenv is required. From a terminal: ./scripts/install_mcp.sh"
        ) from exc

    saved = {key: os.environ[key] for key in _EXPORT_WINS if os.environ.get(key)}
    load_dotenv(_xdg_env_path(), override=True)
    load_dotenv(Path(repo_root) / ".env", override=True)
    os.environ.update(saved)
    _loaded = True
