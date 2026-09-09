"""Merge (and unmerge) the bridge's hook entries in ~/.claude/settings.json.

Driven by `bridge install-hooks` / `bridge uninstall-hooks`. Existing hook
entries are left untouched; ours are identified by the absolute path of the
hooks/ directory in this checkout. A timestamped backup of settings.json is
written before any change.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"

# event name -> (hook script filename, hook timeout in seconds or None for default)
# The Stop hook may block for up to `poll_minutes` waiting for a command, so it
# needs a generous timeout; keep poll_minutes comfortably under this.
HOOKS = {
    "SessionStart": ("session_start.py", None),
    "Stop": ("stop.py", 3600),
    "SessionEnd": ("session_end.py", None),
}


def _hooks_dir() -> Path:
    # src/claude_bridge_telegram/hookinstall.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2] / "hooks"


def _command_for(script: str) -> str:
    # hooks are stdlib-only: run with the system python3, not the project venv,
    # so they start fast and don't depend on uv being on PATH.
    return f"python3 {_hooks_dir() / script}"


def _load() -> dict:
    if SETTINGS.exists():
        return json.loads(SETTINGS.read_text())
    return {}


def _backup() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = SETTINGS.with_name(f"settings.json.bak-{stamp}")
    shutil.copy2(SETTINGS, dst)
    return dst


def _is_ours(entry: dict) -> bool:
    hd = str(_hooks_dir())
    for h in entry.get("hooks", []):
        if hd in h.get("command", ""):
            return True
    return False


def install() -> None:
    if not SETTINGS.exists():
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text("{}\n")
    print(f"backup: {_backup()}")
    data = _load()
    hooks = data.setdefault("hooks", {})

    for event, (script, timeout) in HOOKS.items():
        groups = hooks.setdefault(event, [])
        groups[:] = [g for g in groups if not _is_ours(g)]  # drop stale versions
        hook_entry: dict = {"type": "command", "command": _command_for(script)}
        if timeout is not None:
            hook_entry["timeout"] = timeout
        groups.append({"hooks": [hook_entry]})
        print(f"  + {event}: {_command_for(script)}"
              + (f"  (timeout {timeout}s)" if timeout else ""))

    SETTINGS.write_text(json.dumps(data, indent=2) + "\n")
    print("done. New Claude Code sessions will use the bridge.")


def uninstall() -> None:
    if not SETTINGS.exists():
        print("no settings.json")
        return
    print(f"backup: {_backup()}")
    data = _load()
    hooks = data.get("hooks", {})
    removed = 0
    for event in HOOKS:
        groups = hooks.get(event, [])
        before = len(groups)
        groups[:] = [g for g in groups if not _is_ours(g)]
        removed += before - len(groups)
        if not groups:
            hooks.pop(event, None)
    SETTINGS.write_text(json.dumps(data, indent=2) + "\n")
    print(f"removed {removed} hook group(s).")
