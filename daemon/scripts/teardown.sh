#!/usr/bin/env bash

# Run when the plugin is disabled or removed. Stops and removes the systemd
# user unit; deliberately leaves ~/.config/soundmonkey/config.yml alone so
# re-enabling the plugin later doesn't lose the user's device configuration.

set -uo pipefail

systemctl --user disable --now soundmonkey.service >/dev/null 2>&1 || true
rm -f "$HOME/.config/systemd/user/soundmonkey.service"
systemctl --user daemon-reload >/dev/null 2>&1 || true
