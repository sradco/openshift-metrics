#!/usr/bin/env bash
# Install (or refresh) the local .venv from the locked dependency set.
#
# Prefer this over pip at MCP start time. Run once after clone / when
# pyproject.toml or uv.lock changes, then point Cursor at run_mcp.sh.
#
# Usage:
#   ./scripts/install_mcp.sh           # runtime deps
#   ./scripts/install_mcp.sh --dev     # + pytest
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DEV=0
for arg in "$@"; do
  case "$arg" in
    --dev|-d) DEV=1 ;;
    -h|--help)
      echo "Usage: $0 [--dev]"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'EOF'
openshift-metrics: 'uv' is required to install a locked environment.

Install uv: https://docs.astral.sh/uv/getting-started/installation/
  curl -LsSf https://astral.sh/uv/install.sh | sh

Then re-run: ./scripts/install_mcp.sh
EOF
  exit 1
fi

if [[ ! -f "$REPO_ROOT/uv.lock" ]]; then
  echo "openshift-metrics: missing uv.lock — run 'uv lock' in the repo root." >&2
  exit 1
fi

echo "openshift-metrics: syncing .venv from uv.lock (frozen)..." >&2
if [[ "$DEV" -eq 1 ]]; then
  uv sync --frozen --extra dev
else
  uv sync --frozen
fi

echo "openshift-metrics: install complete (.venv ready)." >&2
echo "Next: point Cursor MCP at $REPO_ROOT/scripts/run_mcp.sh" >&2
