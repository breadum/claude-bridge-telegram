"""Shared helpers for the bridge hooks.

STDLIB ONLY. These scripts run from ~/.claude/settings.json with the system
python3 on every Stop / SessionStart / SessionEnd, so they must start fast and
never import the project package or third-party libs.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import secrets
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------
# paths (mirror of claude_bridge_telegram.paths, kept standalone on purpose)
# --------------------------------------------------------------------------

def root() -> Path:
    env = os.environ.get("CLAUDE_TG_BRIDGE_HOME")
    return Path(env).expanduser() if env else Path.home() / ".claude" / "bridge"


ROOT = root()
REGISTER = ROOT / "register"
SESSIONS = ROOT / "sessions"
INBOX = ROOT / "inbox"
OUTBOX = ROOT / "outbox"
END = ROOT / "end"
COUNTERS = ROOT / "counters"
CONFIG_FILE = ROOT / "config.json"


def ensure_dirs() -> None:
    for d in (REGISTER, SESSIONS, INBOX, OUTBOX, END, COUNTERS):
        d.mkdir(parents=True, exist_ok=True)


def inbox_file(sid: str) -> Path:
    return INBOX / f"{sid}.jsonl"


def session_file(sid: str) -> Path:
    return SESSIONS / f"{sid}.json"


def counter_file(sid: str) -> Path:
    return COUNTERS / sid


def queue_outbox(sid: str, role: str, text: str) -> None:
    """Drop a message for the broker to deliver to this session's topic.
    role: "user" | "assistant" | "note". Filenames sort chronologically."""
    d = OUTBOX / sid
    d.mkdir(parents=True, exist_ok=True)
    name = f"{ts()}-{secrets.token_hex(2)}.json"
    (d / name).write_text(
        json.dumps({"role": role, "text": text}, ensure_ascii=False)
    )


# --------------------------------------------------------------------------
# config (plain JSON, written by `bridge setup`)
# --------------------------------------------------------------------------

_DEFAULTS = {"poll_minutes": 5.0, "grace_seconds": 5.0, "max_reinjections": 50}


def load_config() -> dict:
    cfg = dict(_DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    if v := os.environ.get("CLAUDE_TG_POLL_MINUTES"):
        cfg["poll_minutes"] = float(v)
    if v := os.environ.get("CLAUDE_TG_GRACE_SECONDS"):
        cfg["grace_seconds"] = float(v)
    if v := os.environ.get("CLAUDE_TG_MAX_REINJECTIONS"):
        cfg["max_reinjections"] = int(v)
    return cfg


# --------------------------------------------------------------------------
# hook io
# --------------------------------------------------------------------------

def read_event() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}


def emit(obj: dict | None = None) -> None:
    """Print the hook's JSON result and exit 0."""
    sys.stdout.write(json.dumps(obj or {}, ensure_ascii=False))
    sys.stdout.flush()
    raise SystemExit(0)


def block(reason: str) -> None:
    """Feed `reason` back into the session as the next instruction."""
    emit({"decision": "block", "reason": reason})


# --------------------------------------------------------------------------
# locking + inbox queue
# --------------------------------------------------------------------------

@contextlib.contextmanager
def locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    with open(lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def pop_inbox(sid: str) -> dict | None:
    """Remove and return the oldest queued item, or None."""
    f = inbox_file(sid)
    with locked(f):
        if not f.exists():
            return None
        lines = [ln for ln in f.read_text().splitlines() if ln.strip()]
        if not lines:
            return None
        first, rest = lines[0], lines[1:]
        f.write_text(("\n".join(rest) + "\n") if rest else "")
    try:
        return json.loads(first)
    except json.JSONDecodeError:
        return None


def clear_inbox(sid: str) -> None:
    f = inbox_file(sid)
    with locked(f):
        f.write_text("")


# --------------------------------------------------------------------------
# transcript
# --------------------------------------------------------------------------

def last_assistant_text(transcript_path: str) -> str:
    """Join the text blocks of the final assistant message in the transcript."""
    p = Path(transcript_path) if transcript_path else None
    if not p or not p.exists():
        return "(transcript unavailable)"

    best: list[str] = []
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        msg = obj.get("message") or {}
        content = msg.get("content")
        texts: list[str] = []
        if isinstance(content, str):
            texts = [content]
        elif isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    texts.append(blk.get("text", ""))
        texts = [t for t in texts if t.strip()]
        if texts:
            best = texts  # keep overwriting -> ends on the last one
    return "\n\n".join(best) if best else "(no text in final response)"


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------

def ts() -> str:
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f".{int(time.time()*1000)%1000:03d}"


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_json_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)
