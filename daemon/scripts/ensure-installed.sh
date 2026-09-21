#!/usr/bin/env bash

# Idempotent: safe to run every time the plugin loads, not just on first
# install. Builds the daemon's venv, seeds a user config from the shipped
# example if one doesn't exist yet, installs/updates the systemd user unit,
# and starts it - so end-user install is genuinely just
# `omarchy plugin add <url> --enable`, no terminal steps required.
#
# The venv is built OUTSIDE the plugin's own directory (via
# UV_PROJECT_ENVIRONMENT), not at the more obvious daemon/.venv. The
# installed plugin directory is exactly what Omarchy's shell watches for
# live plugin reload - a venv built inside it means every install writes
# files the watcher sees as "the plugin changed", triggering a reload that
# recreates Service.qml, which re-runs this script, which writes to the
# venv again, forever. Confirmed live: this produced a self-sustaining
# reload loop that pegged the shell at ~25% CPU and made its IPC
# unresponsive until the plugin was force-removed.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DAEMON_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
UNIT_SRC="$DAEMON_DIR/systemd/soundmonkey.service"
UNIT_DST="$HOME/.config/systemd/user/soundmonkey.service"
CONFIG_DIR="$HOME/.config/soundmonkey"
VENV_DIR="$HOME/.local/state/soundmonkey/venv"

if ! command -v uv >/dev/null 2>&1; then
  echo "ensure-installed: uv is required (https://docs.astral.sh/uv/) but was not found on PATH" >&2
  exit 1
fi

mkdir -p "$(dirname "$VENV_DIR")"
( cd "$DAEMON_DIR" && UV_PROJECT_ENVIRONMENT="$VENV_DIR" uv sync --no-dev )

mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/config.yml" ]]; then
  cp "$DAEMON_DIR/config.example.yml" "$CONFIG_DIR/config.yml"
fi

mkdir -p "$(dirname "$UNIT_DST")"
if ! cmp -s "$UNIT_SRC" "$UNIT_DST" 2>/dev/null; then
  cp "$UNIT_SRC" "$UNIT_DST"
  systemctl --user daemon-reload
fi

systemctl --user enable --now soundmonkey.service
