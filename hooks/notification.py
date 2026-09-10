#!/usr/bin/env python3
"""Notification hook: mirror "the session wants your attention" to the topic.

Claude Code fires this when it needs permission for a tool or is otherwise
waiting on the user. Non-blocking — queues one line and exits.

The plain idle nudge ("Claude is waiting for your input") is dropped: the Stop
hook already mirrored the response, so the topic already shows it's your turn.
Actionable notifications (permission requests, AskUserQuestion) are forwarded so
you know to look at the terminal — or answer in the topic, which lands in the
prompt queue.
"""

from __future__ import annotations

import _bridge_common as bc

_SKIP = ("waiting for your input",)


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    if not sid or not bc.session_file(sid).exists():
        bc.emit()

    msg = (ev.get("message") or ev.get("title") or "").strip()
    if not msg or any(s in msg.lower() for s in _SKIP):
        bc.emit()

    bc.queue_outbox(sid, "event", msg)
    bc.emit()


if __name__ == "__main__":
    main()
