#!/usr/bin/env python3
"""SessionStart hook: register the session so the broker creates a Telegram topic.

Also records this session's [uds-messaging] socket + token so the broker can
inject Telegram messages back into the running session. On `resume`/`clear` the
session's pid (and therefore its socket path) may have changed, so we always
re-write the register file; the broker refreshes the stored socket/token and
does not create a second topic.
"""

from __future__ import annotations

import os

import _bridge_common as bc


def _clean(s: str) -> str:
    return "".join(ch for ch in s if ch.isprintable() and ch not in "\r\n")


def cwd_base(cwd: str) -> str:
    return _clean(os.path.basename(cwd.rstrip("/")) or "session")[:60]


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    cwd = ev.get("cwd") or os.getcwd()
    if not sid:
        bc.emit()

    bc.ensure_dirs()
    base = cwd_base(cwd)
    bc.write_json_atomic(
        bc.REGISTER / f"{sid}.json",
        {
            "session_id": sid,
            "label": f"{base}-{sid[:4]}"[:120],  # for `bridge status` / logs
            "base": base,                        # topic-name prefix
            "cwd": cwd,
            "source": ev.get("source"),
            # how the broker talks back to this running session:
            "messaging_socket": os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET", ""),
            "messaging_token": os.environ.get("CLAUDE_CODE_MESSAGING_TOKEN", ""),
            "pid": os.environ.get("CLAUDE_PID", ""),
            "ts": bc.ts(),
        },
    )
    bc.emit()


if __name__ == "__main__":
    main()
