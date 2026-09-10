#!/usr/bin/env python3
"""Stop hook: mirror the turn's final response to Telegram. Non-blocking.

This hook used to block waiting for a command from Telegram. It no longer does:
the broker injects commands straight into the running session over its
[uds-messaging] socket, so the hook just ships the response out and exits.
"""

from __future__ import annotations

import _bridge_common as bc


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    # Only act for sessions the broker has a topic for. A session that started
    # before `bridge install-hooks` has no record here -> stay silent.
    if not sid or not bc.session_file(sid).exists():
        bc.emit()

    tp = ev.get("transcript_path", "")
    bc.queue_outbox(sid, "assistant", bc.last_assistant_text(tp), ai_title=bc.last_ai_title(tp))
    bc.emit()


if __name__ == "__main__":
    main()
