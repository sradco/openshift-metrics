#!/usr/bin/env bash
# Stdio launcher for mcpchecker evals (resolves repo root).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "${ROOT}/scripts/run_mcp.sh"
