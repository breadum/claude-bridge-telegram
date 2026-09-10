"""Runtime directory layout for the bridge.

All mutable state lives under ~/.claude/bridge (override with CLAUDE_TG_BRIDGE_HOME),
kept separate from the code checkout so the daemon and hooks share one location.
"""

from __future__ import annotations

import os
from pathlib import Path


def _root() -> Path:
    env = os.environ.get("CLAUDE_TG_BRIDGE_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".claude" / "bridge"


ROOT = _root()

STATE = ROOT / "state"
OFFSET_FILE = STATE / "offset"
PID_FILE = STATE / "broker.pid"
LOG_FILE = STATE / "broker.log"

REGISTER = ROOT / "register"      # session_start drops <sid>.json here
SESSIONS = ROOT / "sessions"      # broker writes <sid>.json (label, thread_id, socket, ...)
THREADS = ROOT / "threads"        # <thread_id> -> file whose content is the sid
INBOX = ROOT / "inbox"            # <sid>.jsonl : commands that failed to inject, awaiting retry
OUTBOX = ROOT / "outbox"          # <sid>/<ts>.json : queued outbound messages
END = ROOT / "end"                # session_end drops <sid>.json here

ALL_DIRS = [STATE, REGISTER, SESSIONS, THREADS, INBOX, OUTBOX, END]


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def inbox_file(sid: str) -> Path:
    return INBOX / f"{sid}.jsonl"


def outbox_dir(sid: str) -> Path:
    return OUTBOX / sid


def session_file(sid: str) -> Path:
    return SESSIONS / f"{sid}.json"


def thread_file(thread_id: int | str) -> Path:
    return THREADS / str(thread_id)
