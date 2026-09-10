"""Shared helpers for the bridge hooks.

STDLIB ONLY. These scripts run from ~/.claude/settings.json with the system
python3 on every SessionStart / UserPromptSubmit / Stop / SessionEnd, so they
must start fast and never import the project package or third-party libs.

All four hooks are non-blocking: they write a small file under paths.ROOT and
exit. The broker does everything else (topics, Telegram, injecting commands
back into the session over its [uds-messaging] socket).
"""

from __future__ import annotations

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
OUTBOX = ROOT / "outbox"
END = ROOT / "end"


def ensure_dirs() -> None:
    for d in (REGISTER, SESSIONS, OUTBOX, END):
        d.mkdir(parents=True, exist_ok=True)


def session_file(sid: str) -> Path:
    return SESSIONS / f"{sid}.json"


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
