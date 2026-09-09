#!/usr/bin/env python3
"""SessionStart hook: register the session so the broker creates a Telegram topic.

Idempotent: on `resume`/`clear` the broker sees an existing session record and
skips creating a duplicate topic.
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
    # Don't re-register a session the broker already knows about.
    if bc.session_file(sid).exists():
        bc.emit()

    base = cwd_base(cwd)
    bc.write_json_atomic(
        bc.REGISTER / f"{sid}.json",
        {
            "session_id": sid,
            "label": f"{base}-{sid[:4]}"[:120],  # for `bridge status` / logs
            "base": base,                        # topic-name prefix
            "cwd": cwd,
            "source": ev.get("source"),
            "ts": bc.ts(),
        },
    )
    bc.emit()


if __name__ == "__main__":
    main()
