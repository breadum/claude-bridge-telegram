#!/usr/bin/env python3
"""Stop hook: ship the last response to Telegram, then (optionally) wait for a
command to inject back into the session.

Flow per call:
  1. queue the final assistant text in outbox/<sid>/ (broker sends it to the topic)
  2. if the session is "armed" (a command has been sent from Telegram, or
     /arm was used) wait up to poll_minutes for the next command; otherwise
     only glance for grace_seconds so normal terminal use isn't blocked
  3. a queued command  -> {"decision":"block","reason": <text>}  (session continues)
     nothing / timeout  -> {}                                    (session stops)

`stop_hook_active` is true when we're already resuming from a previous inject:
do a single non-blocking pass so chained commands run, then stop.
"""

from __future__ import annotations

import time

import _bridge_common as bc


def push_response(sid: str, transcript_path: str) -> None:
    bc.queue_outbox(sid, "assistant", bc.last_assistant_text(transcript_path))


def bump_counter(sid: str) -> int:
    f = bc.counter_file(sid)
    n = 0
    if f.exists():
        try:
            n = int(f.read_text().strip() or "0")
        except ValueError:
            n = 0
    n += 1
    f.write_text(str(n))
    return n


def reset_counter(sid: str) -> None:
    bc.counter_file(sid).write_text("0")


def take_command(sid: str) -> dict | None:
    """Pop the next inbox item, skipping empty ones. Returns the item dict
    (which may be a control item) or None if the queue is empty."""
    while True:
        item = bc.pop_inbox(sid)
        if item is None:
            return None
        if item.get("control"):
            return item
        if (item.get("text") or "").strip():
            return item
        # empty text -> discard, keep looking


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    if not sid:
        bc.emit()

    # Only act for sessions the broker has registered a topic for. A session
    # that started before `bridge install-hooks` (or whose SessionStart didn't
    # register) has no record here -> stay completely silent.
    if not bc.session_file(sid).exists():
        bc.emit()

    bc.ensure_dirs()
    cfg = bc.load_config()
    stop_active = bool(ev.get("stop_hook_active"))

    push_response(sid, ev.get("transcript_path", ""))

    maxr = int(cfg["max_reinjections"])
    if stop_active and _count(sid) >= maxr:
        _note(sid, f"bridge: hit max_reinjections ({maxr}); stopping. Send another message to resume.")
        reset_counter(sid)
        bc.emit()

    # --- single pass when resuming from a previous inject -----------------
    if stop_active:
        rec = bc.read_json(bc.session_file(sid)) or {}
        if not rec.get("paused") and rec.get("status") != "ended":
            item = take_command(sid)
            if item and item.get("control") == "stop":
                bc.clear_inbox(sid)
            elif item:
                bump_counter(sid)
                bc.block(item["text"])
        reset_counter(sid)
        bc.emit()

    # --- fresh turn end: wait for a command ----------------------------
    grace = float(cfg.get("grace_seconds", 5))
    poll = float(cfg["poll_minutes"]) * 60.0
    start = time.monotonic()

    while True:
        rec = bc.read_json(bc.session_file(sid)) or {}
        if rec.get("status") == "ended":
            bc.clear_inbox(sid)
            reset_counter(sid)
            bc.emit()

        armed = bool(rec.get("armed"))
        window = poll if armed else grace

        # While paused we keep waiting but don't consume commands; the timeout
        # still applies so the terminal isn't held forever.
        if not rec.get("paused"):
            item = take_command(sid)
            if item and item.get("control") == "stop":
                bc.clear_inbox(sid)
                reset_counter(sid)
                bc.emit()
            if item:
                bump_counter(sid)
                bc.block(item["text"])

        if (time.monotonic() - start) >= window:
            reset_counter(sid)
            bc.emit()

        time.sleep(0.5)


def _count(sid: str) -> int:
    f = bc.counter_file(sid)
    if not f.exists():
        return 0
    try:
        return int(f.read_text().strip() or "0")
    except ValueError:
        return 0


def _note(sid: str, msg: str) -> None:
    bc.queue_outbox(sid, "note", msg)


if __name__ == "__main__":
    main()
