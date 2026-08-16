#!/usr/bin/env bash
# Launch the openshift-metrics MCP server for Cursor / Claude Code (stdio).
#
# Creates .venv from uv.lock on first start only. Later starts exec
# Python (no network). Failed uv sync or a failed import check exits
# non-zero (stderr is not swallowed). If uv.lock drifted, prints a
# hint to run ./scripts/install_mcp.sh — does not sync in-process.
#
# Usage in MCP config (absolute path recommended):
#   "command": "/path/to/openshift-metrics/scripts/run_mcp.sh"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/common.sh
source "${REPO_ROOT}/scripts/lib/common.sh"
cd "$REPO_ROOT"

VENV_PY="$(require_venv "$REPO_ROOT")"

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
# Force stdio so a leftover MCP_TRANSPORT in .env cannot start HTTP.
exec "$VENV_PY" -m mcp_server --transport stdio
