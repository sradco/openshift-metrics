#!/usr/bin/env bash
# HTTP MCP launcher. First start may create .venv (same as run_mcp.sh).
# Requires MCP_HTTP_TOKEN (enforced in Python). For local Cursor/Claude
# without a long-lived process, use run_mcp.sh (stdio).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/common.sh
source "${REPO_ROOT}/scripts/lib/common.sh"
cd "$REPO_ROOT"

VENV_PY="$(require_venv "$REPO_ROOT")"

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

# Host/port/path/token come from the environment / .env (loaded in Python).
exec "$VENV_PY" -m mcp_server --transport streamable-http
