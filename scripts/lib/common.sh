#!/usr/bin/env bash
# Shared helpers for MCP launchers (sourced by run_mcp.sh / run_mcp_http.sh).
# Env files are loaded in Python (mcp_server.runtime_env), not here.
# shellcheck shell=bash

require_venv() {
  local repo_root="$1"
  local venv_py="${repo_root}/.venv/bin/python"
  if [[ ! -x "$venv_py" ]]; then
    cat >&2 <<EOF
openshift-metrics: .venv is missing or incomplete.

Install a locked environment once (no network on MCP start):
  cd ${repo_root}
  ./scripts/install_mcp.sh

Then restart the openshift-metrics MCP (or re-run the HTTP launcher).
EOF
    return 1
  fi
  printf '%s\n' "$venv_py"
}
