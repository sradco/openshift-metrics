#!/usr/bin/env bash
# Shared helpers for MCP launchers (sourced by run_mcp.sh / run_mcp_http.sh).
# Env files are loaded in Python (mcp_server.runtime_env), not here.
# shellcheck shell=bash

# GUI apps (Cursor / Claude) often omit ~/.local/bin from PATH.
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"

_uv_lock_hash() {
  sha256sum "$1" | awk '{print $1}'
}

_uv_lock_stamp() {
  printf '%s\n' "${1}/.venv/.uv-lock-hash"
}

write_uv_lock_stamp() {
  local repo_root="$1"
  mkdir -p "${repo_root}/.venv"
  _uv_lock_hash "${repo_root}/uv.lock" >"$(_uv_lock_stamp "$repo_root")"
}

_resolve_uv() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi
  local candidate
  for candidate in "${HOME}/.local/bin/uv" /usr/local/bin/uv "${HOME}/.cargo/bin/uv"; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

_uv_missing_msg() {
  local repo_root="$1"
  cat >&2 <<EOF
openshift-metrics: 'uv' was not found (PATH, ~/.local/bin, ~/.cargo/bin).

Install uv: https://docs.astral.sh/uv/getting-started/installation/
  curl -LsSf https://astral.sh/uv/install.sh | sh

Then from a terminal:
  cd ${repo_root}
  ./scripts/install_mcp.sh
EOF
}

# First start only: create .venv from uv.lock. Lock drift is not synced
# here (GUI spawn); warn and keep the existing venv.
ensure_venv() {
  local repo_root="$1"
  local lock="${repo_root}/uv.lock"
  local venv_py="${repo_root}/.venv/bin/python"
  local stored want uv_bin

  if [[ ! -f "$lock" ]]; then
    echo "openshift-metrics: missing uv.lock — pull the repo, then retry." >&2
    return 1
  fi

  if [[ ! -x "$venv_py" ]]; then
    if ! uv_bin="$(_resolve_uv)"; then
      _uv_missing_msg "$repo_root"
      return 1
    fi
    echo "openshift-metrics: creating .venv from uv.lock..." >&2
    if ! (cd "$repo_root" && "$uv_bin" sync --frozen); then
      echo "openshift-metrics: uv sync --frozen failed (see output above)." >&2
      echo "From a terminal: cd ${repo_root} && ./scripts/install_mcp.sh" >&2
      return 1
    fi
    write_uv_lock_stamp "$repo_root"
    return 0
  fi

  want="$(_uv_lock_hash "$lock")"
  if [[ -f "$(_uv_lock_stamp "$repo_root")" ]]; then
    stored="$(cat "$(_uv_lock_stamp "$repo_root")")"
    if [[ "$stored" == "$want" ]]; then
      return 0
    fi
  fi

  cat >&2 <<EOF
openshift-metrics: uv.lock does not match this .venv.
From a terminal (do not rely on Cursor/Claude spawn):
  cd ${repo_root}
  ./scripts/install_mcp.sh
Starting with the existing .venv.
EOF
}

# Fail loudly if the venv cannot import the server (missing wheels, etc.).
verify_runtime_imports() {
  local repo_root="$1"
  local venv_py="$2"
  local err
  local ec=0
  err="$(
    PYTHONPATH="${repo_root}/src${PYTHONPATH:+:$PYTHONPATH}" \
      "$venv_py" -c "import mcp_server.server" 2>&1
  )" || ec=$?
  if [[ "$ec" -ne 0 ]]; then
    cat >&2 <<EOF
openshift-metrics: MCP cannot start — Python import failed
(missing or broken packages in .venv).

${err}

From a terminal:
  cd ${repo_root}
  ./scripts/install_mcp.sh

Then restart the openshift-metrics MCP.
EOF
    return 1
  fi
}

require_venv() {
  local repo_root="$1"
  local venv_py="${repo_root}/.venv/bin/python"
  ensure_venv "$repo_root" || return 1
  if [[ ! -x "$venv_py" ]]; then
    echo "openshift-metrics: .venv/bin/python is missing." >&2
    return 1
  fi
  verify_runtime_imports "$repo_root" "$venv_py" || return 1
  printf '%s\n' "$venv_py"
}
