#!/usr/bin/env python3
"""SessionEnd hook: tell the broker the session is over."""

from __future__ import annotations

import _bridge_common as bc


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    if not sid:
        bc.emit()
    bc.ensure_dirs()
    bc.clear_busy(sid)
    bc.write_json_atomic(
        bc.END / f"{sid}.json",
        {"session_id": sid, "reason": ev.get("reason"), "ts": bc.ts()},
    )
    bc.emit()


if __name__ == "__main__":
    main()
