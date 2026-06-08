#!/usr/bin/env bash
set -euo pipefail

PREFERRED_PYTHON="${1:-}"

log() {
  printf '%s\n' "$*" >&2
}

resolve_python() {
  local candidate="$1"

  if [ -z "$candidate" ]; then
    return 1
  fi

  if [ -x "$candidate" ]; then
    printf '%s\n' "$candidate"
    return 0
  fi

  command -v "$candidate" 2>/dev/null
}

is_python311() {
  local python_bin="$1"

  "$python_bin" - <<'PY' >/dev/null 2>&1
import sys

raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)
PY
}

add_pyenv_candidates() {
  if ! command -v pyenv >/dev/null 2>&1; then
    return 0
  fi

  local pyenv_root
  pyenv_root="$(pyenv root 2>/dev/null || true)"
  if [ -z "$pyenv_root" ] || [ ! -d "$pyenv_root/versions" ]; then
    return 0
  fi

  find "$pyenv_root/versions" -path '*/bin/python3.11' -type f 2>/dev/null || true
}

build_candidates() {
  if [ -n "${ASTRATRADE_PYTHON:-}" ]; then
    printf '%s\n' "$ASTRATRADE_PYTHON"
  fi

  if [ -n "$PREFERRED_PYTHON" ]; then
    printf '%s\n' "$PREFERRED_PYTHON"
  fi

  if command -v uv >/dev/null 2>&1; then
    uv python find 3.11 2>/dev/null || true
  fi

  printf '%s\n' \
    python3.11 \
    "$HOME/.local/bin/python3.11" \
    "$HOME/.pyenv/shims/python3.11" \
    /opt/homebrew/opt/python@3.11/bin/python3.11 \
    /usr/local/opt/python@3.11/bin/python3.11 \
    /usr/bin/python3.11 \
    /usr/local/bin/python3.11

  add_pyenv_candidates
}

find_python311() {
  local candidate
  local resolved

  while IFS= read -r candidate; do
    if resolved="$(resolve_python "$candidate")" && is_python311 "$resolved"; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done < <(build_candidates | awk 'NF && !seen[$0]++')

  return 1
}

run_with_sudo_if_needed() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    log "sudo is required to install Python 3.11 with this package manager."
    return 1
  fi
}

install_with_uv() {
  if ! command -v uv >/dev/null 2>&1; then
    return 1
  fi

  log "Python 3.11 not found. Installing Python 3.11 with uv..."
  uv python install 3.11
}

install_with_brew() {
  if ! command -v brew >/dev/null 2>&1; then
    return 1
  fi

  log "Python 3.11 not found. Installing python@3.11 with Homebrew..."
  brew install python@3.11
}

install_with_linux_package_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    log "Python 3.11 not found. Installing Python 3.11 with apt-get..."
    run_with_sudo_if_needed apt-get update || return 1
    run_with_sudo_if_needed apt-get install -y python3.11 python3.11-venv python3.11-dev || return 1
    return 0
  fi

  if command -v dnf >/dev/null 2>&1; then
    log "Python 3.11 not found. Installing Python 3.11 with dnf..."
    run_with_sudo_if_needed dnf install -y python3.11 python3.11-devel python3.11-pip || return 1
    return 0
  fi

  if command -v yum >/dev/null 2>&1; then
    log "Python 3.11 not found. Installing Python 3.11 with yum..."
    run_with_sudo_if_needed yum install -y python3.11 python3.11-devel python3.11-pip || return 1
    return 0
  fi

  if command -v zypper >/dev/null 2>&1; then
    log "Python 3.11 not found. Installing Python 3.11 with zypper..."
    run_with_sudo_if_needed zypper --non-interactive install python311 python311-devel python311-pip || return 1
    return 0
  fi

  return 1
}

install_with_pyenv() {
  if ! command -v pyenv >/dev/null 2>&1; then
    return 1
  fi

  local latest_patch
  latest_patch="$(
    pyenv install --list |
      sed 's/^[[:space:]]*//' |
      grep -E '^3\.11\.[0-9]+$' |
      tail -n 1 || true
  )"

  if [ -z "$latest_patch" ]; then
    return 1
  fi

  log "Python 3.11 not found. Installing Python $latest_patch with pyenv..."
  pyenv install -s "$latest_patch"
}

install_python311() {
  local os_name
  os_name="$(uname -s)"

  install_with_uv && return 0

  case "$os_name" in
    Darwin)
      install_with_brew && return 0
      ;;
    Linux)
      install_with_linux_package_manager && return 0
      ;;
  esac

  install_with_pyenv && return 0

  return 1
}

if python_bin="$(find_python311)"; then
  printf '%s\n' "$python_bin"
  exit 0
fi

if install_python311 && python_bin="$(find_python311)"; then
  printf '%s\n' "$python_bin"
  exit 0
fi

log "Could not find or install Python 3.11 automatically."
log "Install Python 3.11 manually, or rerun with PYTHON=/absolute/path/to/python3.11 make setup."
exit 1
