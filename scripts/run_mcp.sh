#!/usr/bin/env bash
# Launch the openshift-metrics MCP server for Cursor / Claude Code.
#
# Usage in MCP config (absolute path recommended):
#   "command": "/path/to/openshift-metrics/scripts/run_mcp.sh"
#
# Credentials (first match wins):
#   1) Already-exported CLIENTID / CLIENTSECRET
#   2) $REPO_ROOT/.env
#   3) ${XDG_CONFIG_HOME:-$HOME/.config}/openshift-metrics/env
#
# After git pull: restart the MCP in Cursor. This script refreshes the
# venv when requirements.txt changes; code/recipes load from the checkout.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="${REPO_ROOT}/.venv"
VENV_PY="${VENV_DIR}/bin/python"
REQS="${REPO_ROOT}/requirements.txt"
REQS_STAMP="${VENV_DIR}/.requirements.sha256"

# Parse KEY=VAL env files without `source` (avoids executing shell from .env).
load_env_file() {
  local file="$1"
  local line key value
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Trim CR and skip blanks/comments
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == export\ * ]] && line="${line#export }"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    # Strip optional matching quotes
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    # Only simple env keys
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    printf -v "$key" '%s' "$value"
    export "$key"
  done <"$file"
}

reqs_checksum() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$REQS" | awk '{print $1}'
  else
    # macOS / BSD
    shasum -a 256 "$REQS" | awk '{print $1}'
  fi
}

ensure_venv_deps() {
  local need_install=0
  local checksum

  if [[ ! -x "$VENV_PY" ]]; then
    echo "openshift-metrics: creating .venv and installing dependencies..." >&2
    python3 -m venv "$VENV_DIR"
    "$VENV_PY" -m pip install -q --upgrade pip
    need_install=1
  fi

  checksum="$(reqs_checksum)"
  if [[ ! -f "$REQS_STAMP" ]] || [[ "$(cat "$REQS_STAMP")" != "$checksum" ]]; then
    if [[ "$need_install" -eq 0 ]]; then
      echo "openshift-metrics: requirements.txt changed; updating dependencies..." >&2
    fi
    need_install=1
  fi

  if [[ "$need_install" -eq 1 ]]; then
    "$VENV_PY" -m pip install -q -r "$REQS"
    printf '%s\n' "$checksum" >"$REQS_STAMP"
  fi
}

# Preserve already-exported credentials, then load files (repo .env overrides
# user config). Exported values always win.
_PRE_PROM_URL="${PROM_URL-}"
_PRE_CLIENTID="${CLIENTID-}"
_PRE_CLIENTSECRET="${CLIENTSECRET-}"
load_env_file "${XDG_CONFIG_HOME:-$HOME/.config}/openshift-metrics/env"
load_env_file "${REPO_ROOT}/.env"
if [[ -n "${_PRE_PROM_URL}" ]]; then
  export PROM_URL="${_PRE_PROM_URL}"
fi
if [[ -n "${_PRE_CLIENTID}" ]]; then
  export CLIENTID="${_PRE_CLIENTID}"
fi
if [[ -n "${_PRE_CLIENTSECRET}" ]]; then
  export CLIENTSECRET="${_PRE_CLIENTSECRET}"
fi
unset _PRE_PROM_URL _PRE_CLIENTID _PRE_CLIENTSECRET

ensure_venv_deps

export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV_PY" -m mcp_server
