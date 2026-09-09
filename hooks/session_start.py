#!/usr/bin/env python3
"""SessionStart hook: register the session so the broker creates a Telegram topic.

Idempotent: on `resume`/`clear` the broker sees an existing session record and
skips creating a duplicate topic.
"""

from __future__ import annotations

import os

import _bridge_common as bc


def make_label(cwd: str, sid: str) -> str:
    base = os.path.basename(cwd.rstrip("/")) or "session"
    label = f"{base}-{sid[:4]}"
    label = "".join(ch for ch in label if ch.isprintable() and ch not in "\r\n")
    return label[:120]


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    cwd = ev.get("cwd") or os.getcwd()
    if not sid:
        bc.emit()

    bc.ensure_dirs()
    # Don't re-register a session the broker already knows about.
    if bc.session_file(sid).exists():
        bc.emit()

    bc.write_json_atomic(
        bc.REGISTER / f"{sid}.json",
        {
            "session_id": sid,
            "label": make_label(cwd, sid),
            "cwd": cwd,
            "source": ev.get("source"),
            "ts": bc.ts(),
        },
    )
    bc.emit()


if __name__ == "__main__":
    main()
