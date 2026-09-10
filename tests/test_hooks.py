"""Run the hook scripts the way Claude Code does: as subprocesses fed JSON on stdin."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import _bridge_common as bc

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def run_hook(name: str, event: dict, env: dict, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(env)
    e.update(extra_env or {})
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=e,
        timeout=10,
    )


def test_session_start_writes_register_with_socket(hook_env):
    r = run_hook(
        "session_start.py",
        {"session_id": "sess-A", "cwd": "/home/x/proj", "source": "startup"},
        hook_env,
        {"CLAUDE_CODE_MESSAGING_SOCKET": "/run/x/cc-socks/1.sock",
         "CLAUDE_CODE_MESSAGING_TOKEN": "tkn", "CLAUDE_PID": "4242"},
    )
    assert r.returncode == 0
    reg = json.loads((bc.REGISTER / "sess-A.json").read_text())
    assert reg["base"] == "proj"
    assert reg["messaging_socket"] == "/run/x/cc-socks/1.sock"
    assert reg["messaging_token"] == "tkn"
    assert reg["pid"] == "4242"


def test_stop_hook_silent_for_unregistered_session(hook_env, tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps(
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}}
    ) + "\n")
    r = run_hook("stop.py", {"session_id": "ghost", "transcript_path": str(t)}, hook_env)
    assert r.returncode == 0
    assert not (bc.OUTBOX / "ghost").exists()


def test_stop_hook_mirrors_response_for_registered_session(hook_env, tmp_path):
    bc.write_json_atomic(bc.session_file("sess-B"), {"session_id": "sess-B", "status": "active"})
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps(
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "the answer"}]}}
    ) + "\n")
    r = run_hook("stop.py", {"session_id": "sess-B", "transcript_path": str(t)}, hook_env)
    assert r.returncode == 0
    files = list((bc.OUTBOX / "sess-B").iterdir())
    assert len(files) == 1
    assert json.loads(files[0].read_text()) == {"role": "assistant", "text": "the answer"}


def test_stop_hook_forwards_ai_title(hook_env, tmp_path):
    bc.write_json_atomic(bc.session_file("sess-T"), {"session_id": "sess-T", "status": "active"})
    t = tmp_path / "t.jsonl"
    t.write_text(
        json.dumps({"type": "ai-title", "aiTitle": "old title", "sessionId": "sess-T"}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "hi"}]}}) + "\n"
        + json.dumps({"type": "ai-title", "aiTitle": "새 제목", "sessionId": "sess-T"}) + "\n"
    )
    r = run_hook("stop.py", {"session_id": "sess-T", "transcript_path": str(t)}, hook_env)
    assert r.returncode == 0
    files = list((bc.OUTBOX / "sess-T").iterdir())
    assert json.loads(files[0].read_text()) == {
        "role": "assistant", "text": "hi", "ai_title": "새 제목",
    }


def test_user_prompt_submit_mirrors_when_pending(hook_env):
    bc.write_json_atomic(bc.REGISTER / "sess-C.json", {"session_id": "sess-C"})
    r = run_hook("user_prompt_submit.py", {"session_id": "sess-C", "prompt": "  do it  "}, hook_env)
    assert r.returncode == 0
    files = list((bc.OUTBOX / "sess-C").iterdir())
    assert json.loads(files[0].read_text()) == {"role": "user", "text": "do it"}


def test_notification_hook_mirrors_attention_request(hook_env):
    bc.write_json_atomic(bc.session_file("sess-N"), {"session_id": "sess-N", "status": "active"})
    r = run_hook(
        "notification.py",
        {"session_id": "sess-N", "message": "Claude needs your permission to use Bash"},
        hook_env,
    )
    assert r.returncode == 0
    files = list((bc.OUTBOX / "sess-N").iterdir())
    assert json.loads(files[0].read_text()) == {
        "role": "event", "text": "Claude needs your permission to use Bash",
    }


def test_notification_hook_skips_idle_nudge(hook_env):
    bc.write_json_atomic(bc.session_file("sess-N2"), {"session_id": "sess-N2", "status": "active"})
    r = run_hook(
        "notification.py",
        {"session_id": "sess-N2", "message": "Claude is waiting for your input"},
        hook_env,
    )
    assert r.returncode == 0
    assert not (bc.OUTBOX / "sess-N2").exists()


def test_notification_hook_silent_for_unregistered_session(hook_env):
    r = run_hook("notification.py", {"session_id": "ghostN", "message": "hi"}, hook_env)
    assert r.returncode == 0
    assert not (bc.OUTBOX / "ghostN").exists()


def test_session_end_writes_end_file(hook_env):
    r = run_hook("session_end.py", {"session_id": "sess-D", "reason": "exit"}, hook_env)
    assert r.returncode == 0
    end = json.loads((bc.END / "sess-D.json").read_text())
    assert end["session_id"] == "sess-D"
    assert end["reason"] == "exit"
