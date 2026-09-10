#!/usr/bin/env python3
"""UserPromptSubmit hook: mirror the user's prompt into the session's topic.

Together with the Stop hook (which mirrors Claude's reply) this puts the whole
back-and-forth in Telegram. Fast and non-blocking — just drops a file.
"""

from __future__ import annotations

import _bridge_common as bc


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    prompt = (ev.get("prompt") or "").strip()
    if not sid or not prompt:
        bc.emit()
    # queue if the session is registered, or registration is still pending
    # (SessionStart fired, broker hasn't made the topic yet)
    registered = bc.session_file(sid).exists()
    pending = (bc.REGISTER / f"{sid}.json").exists()
    if registered or pending:
        bc.queue_outbox(sid, "user", prompt)
        bc.mark_busy(sid)  # a turn is now running; Stop clears it
    bc.emit()


if __name__ == "__main__":
    main()
