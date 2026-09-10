#!/usr/bin/env bash
# Install the broker as a systemd --user service so it runs at boot without login.
#
#   ./service/install.sh
#
# The repo may live anywhere: this script derives every path from its own
# location and renders service/claude-bridge-telegram.service.in into a concrete
# unit file. Idempotent — re-run it after editing the template or moving/renaming
# the repo (a move also needs `bridge install-hooks` again).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT="claude-bridge-telegram.service"
TEMPLATE="$REPO_DIR/service/$UNIT.in"
DEST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
BRIDGE_BIN="$REPO_DIR/.venv/bin/bridge"

if [[ ! -x "$BRIDGE_BIN" ]]; then
    echo "!! $BRIDGE_BIN not found — run 'uv sync' in $REPO_DIR first" >&2
    exit 1
fi
if [[ ! -f "$TEMPLATE" ]]; then
    echo "!! template missing: $TEMPLATE" >&2
    exit 1
fi

mkdir -p "$DEST_DIR"
sed -e "s|@REPO_DIR@|$REPO_DIR|g" \
    -e "s|@BRIDGE_BIN@|$BRIDGE_BIN|g" \
    "$TEMPLATE" > "$DEST_DIR/$UNIT"
chmod 0644 "$DEST_DIR/$UNIT"
echo "installed $DEST_DIR/$UNIT  (repo: $REPO_DIR)"

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"

# keep it running with no active login / after reboot
loginctl enable-linger "$USER" 2>/dev/null || \
    echo "note: could not enable-linger automatically; run 'sudo loginctl enable-linger $USER'"

echo
systemctl --user --no-pager status "$UNIT" | head -6
echo
echo "logs:  journalctl --user -u $UNIT -f     (or: bridge logs -f)"
