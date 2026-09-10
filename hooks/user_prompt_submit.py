#!/usr/bin/env python3
"""UserPromptSubmit hook: mirror the user's prompt into the session's topic.

Together with the Stop hook (which mirrors Claude's reply) this puts the whole
back-and-forth in Telegram. Fast and non-blocking — just drops a file.

A message the user sent from Telegram also fires this hook (the broker injected
it as a peer prompt). The broker already queued that text, so re-queuing it here
would double-post it in the topic. `_is_peer_injection` catches those and skips
the mirror while still marking the turn busy.
"""

from __future__ import annotations

import _bridge_common as bc

# Claude Code wraps a peer-injected message in one of these preambles.
_PEER_PREFIXES = (
    "Another Claude session sent a message",
    "A peer session sent a message",
)


def _is_peer_injection(ev: dict, prompt: str) -> bool:
    if ev.get("promptSource") == "system":
        return True
    origin = ev.get("origin")
    if isinstance(origin, dict) and origin.get("kind") in ("peer", "system"):
        return True
    return prompt.lstrip().startswith(_PEER_PREFIXES)


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    prompt = (ev.get("prompt") or "").strip()
    if not sid or not prompt:
        bc.emit()
    # act if the session is registered, or registration is still pending
    # (SessionStart fired, broker hasn't made the topic yet)
    if bc.session_file(sid).exists() or (bc.REGISTER / f"{sid}.json").exists():
        bc.mark_busy(sid)  # a turn is now running; Stop clears it
        if not _is_peer_injection(ev, prompt):
            bc.queue_outbox(sid, "user", prompt)
    bc.emit()


if __name__ == "__main__":
    main()
