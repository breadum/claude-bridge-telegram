#!/usr/bin/env bash
# Install the broker as a systemd --user service so it runs at boot without login.
#
#   ./deploy/install-service.sh
#
# Idempotent: re-run it after editing the unit file or moving the repo.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT="claude-bridge-telegram.service"
DEST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [[ ! -x "$REPO_DIR/.venv/bin/bridge" ]]; then
    echo "!! $REPO_DIR/.venv not found — run 'uv sync' in the repo first" >&2
    exit 1
fi

if [[ "$REPO_DIR" != "$HOME/claude-bridge-telegram" ]]; then
    echo "!! repo is at $REPO_DIR but the unit's ExecStart expects ~/claude-bridge-telegram." >&2
    echo "   Either move the repo there, or edit deploy/$UNIT (ExecStart) before installing." >&2
    exit 1
fi

mkdir -p "$DEST_DIR"
install -m 0644 "$REPO_DIR/deploy/$UNIT" "$DEST_DIR/$UNIT"
echo "installed $DEST_DIR/$UNIT"

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"

# keep it running with no active login / after reboot
loginctl enable-linger "$USER" 2>/dev/null || \
    echo "note: could not enable-linger automatically; run 'sudo loginctl enable-linger $USER'"

echo
systemctl --user --no-pager status "$UNIT" | head -6
echo
echo "logs:  journalctl --user -u $UNIT -f     (or: bridge logs -f)"
