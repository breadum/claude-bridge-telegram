"""`bridge` command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

from . import paths
from .config import Config
from .telegram import Telegram, TelegramError


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bridge", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="configure bot token + chat id interactively")
    sub.add_parser("start", help="start the broker daemon")
    sub.add_parser("stop", help="stop the broker daemon")
    sub.add_parser("restart", help="restart the broker daemon")
    sub.add_parser("run", help="run the broker in the foreground (debug)")
    sub.add_parser("status", help="show broker + session status")
    p_logs = sub.add_parser("logs", help="tail the broker log")
    p_logs.add_argument("-f", "--follow", action="store_true")
    sub.add_parser("install-hooks", help="add bridge hooks to ~/.claude/settings.json")
    sub.add_parser("uninstall-hooks", help="remove bridge hooks from ~/.claude/settings.json")

    args = parser.parse_args(argv)
    {
        "setup": cmd_setup,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "run": cmd_run,
        "status": cmd_status,
        "logs": lambda: cmd_logs(args.follow),
        "install-hooks": cmd_install_hooks,
        "uninstall-hooks": cmd_uninstall_hooks,
    }[args.cmd]()


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------


def cmd_setup() -> None:
    cfg = Config.load()
    token = input(f"Bot token [{_mask(cfg.bot_token)}]: ").strip() or cfg.bot_token
    if not token:
        raise SystemExit("a bot token is required")

    with Telegram(token) as tg:
        me = tg.get_me()
        print(f"  bot: @{me.get('username')} ({me.get('id')})")

        chat_id = _discover_chat_id(tg, cfg.chat_id)
        chat = tg.get_chat(chat_id)
        print(f"  chat: {chat.get('title')} ({chat_id}) type={chat.get('type')}")
        if not chat.get("is_forum"):
            print(
                "  ⚠️  this chat does not have Topics enabled.\n"
                "      Group settings → Topics → enable, then re-run setup."
            )

    poll = input(f"Poll minutes (Stop hook wait) [{cfg.poll_minutes}]: ").strip()
    cfg.bot_token = token
    cfg.chat_id = chat_id
    if poll:
        cfg.poll_minutes = float(poll)
    cfg.save()
    from .config import CONFIG_FILE

    print(f"\nsaved {CONFIG_FILE}")
    print("next: `bridge start`  then  `bridge install-hooks`")


def _discover_chat_id(tg: Telegram, current: int) -> int:
    print("\nLooking for your group... (send a message in the group first if none show)")
    try:
        updates = tg.get_updates(offset=0, timeout=0)
    except TelegramError as e:
        raise SystemExit(f"getUpdates failed: {e}")

    seen: dict[int, str] = {}
    for upd in updates:
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") in ("group", "supergroup"):
            seen[chat["id"]] = chat.get("title", "?")

    if not seen:
        manual = input(f"No groups seen. Enter chat_id manually [{current or ''}]: ").strip()
        if manual:
            return int(manual)
        if current:
            return current
        raise SystemExit("no chat id")

    if len(seen) == 1:
        cid, title = next(iter(seen.items()))
        print(f"  found: {title} ({cid})")
        return cid

    print("  multiple groups seen:")
    items = list(seen.items())
    for i, (cid, title) in enumerate(items):
        print(f"    [{i}] {title} ({cid})")
    idx = int(input("  pick number: ").strip())
    return items[idx][0]


def _mask(token: str) -> str:
    if not token:
        return "unset"
    return token[:6] + "…" + token[-4:]


# --------------------------------------------------------------------------
# daemon control
# --------------------------------------------------------------------------


def cmd_run() -> None:
    from .broker import main as broker_main

    broker_main(foreground=True)


def cmd_start() -> None:
    Config.load().validate()
    if _broker_pid():
        print(f"broker already running (pid {_broker_pid()})")
        return
    paths.ensure_dirs()
    logf = open(paths.LOG_FILE, "a")
    proc = subprocess.Popen(
        [sys.executable, "-m", "claude_tg_bridge.broker"],
        stdout=logf,
        stderr=logf,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(1.0)
    if proc.poll() is not None:
        raise SystemExit(f"broker exited immediately (code {proc.returncode}) — see `bridge logs`")
    print(f"broker started (pid {proc.pid})")


def cmd_stop(quiet: bool = False) -> bool:
    pid = _broker_pid()
    if not pid:
        if not quiet:
            print("broker not running")
        return True
    os.kill(pid, 15)
    # the loop can be parked in a getUpdates long-poll; give it room to unwind
    for _ in range(200):
        if not _alive(pid):
            if not quiet:
                print("broker stopped")
            return True
        time.sleep(0.1)
    print(f"broker still alive (pid {pid}) after SIGTERM; sending SIGKILL")
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        pass
    paths.PID_FILE.unlink(missing_ok=True)
    return True


def cmd_restart() -> None:
    cmd_stop(quiet=True)
    for _ in range(50):
        if _broker_pid() is None:
            break
        time.sleep(0.1)
    cmd_start()


def cmd_status() -> None:
    pid = _broker_pid()
    print(f"broker: {'running pid ' + str(pid) if pid else 'stopped'}")
    if paths.OFFSET_FILE.exists():
        print(f"offset: {paths.OFFSET_FILE.read_text().strip()}")
    cfg = Config.load()
    print(f"chat_id: {cfg.chat_id or 'unset'}   poll_minutes: {cfg.poll_minutes}")
    sess = sorted(paths.SESSIONS.glob("*.json"))
    print(f"\nsessions ({len(sess)}):")
    for f in sess:
        try:
            r = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        inbox = paths.inbox_file(r["session_id"])
        q = sum(1 for line in inbox.read_text().splitlines() if line.strip()) if inbox.exists() else 0
        print(f"  {r['label']:<24} {r['status']:<8} paused={r.get('paused', False)!s:<5} q={q}  {r['cwd']}")


def cmd_logs(follow: bool) -> None:
    if not paths.LOG_FILE.exists():
        print("no log yet")
        return
    os.execvp("tail", ["tail", "-n", "80"] + (["-f"] if follow else []) + [str(paths.LOG_FILE)])


# --------------------------------------------------------------------------
# hook install (delegates to scripts/install_hooks.py logic)
# --------------------------------------------------------------------------


def cmd_install_hooks() -> None:
    from .hookinstall import install

    install()


def cmd_uninstall_hooks() -> None:
    from .hookinstall import uninstall

    uninstall()


# --------------------------------------------------------------------------


def _broker_pid() -> int | None:
    if not paths.PID_FILE.exists():
        return None
    txt = paths.PID_FILE.read_text().strip()
    if txt.isdigit() and _alive(int(txt)):
        return int(txt)
    return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    main()
