"""The broker daemon.

Single long-running process. It is the *only* thing that talks to Telegram:

  * turns SessionStart registrations into forum topics
  * long-polls getUpdates and routes each topic message into inbox/<sid>.jsonl
  * ships outbox/<sid>/*.txt back out to the matching topic
  * handles /status /stop /pause /resume without touching the session

Hooks never call Telegram; they only read/write files under paths.ROOT.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import paths
from .config import Config
from .telegram import Telegram, TelegramError, send_with_retry

log = logging.getLogger("bridge.broker")

# getUpdates long-poll seconds. Also the worst-case latency for shipping a
# response to Telegram, since the loop spends most of its time parked here.
POLL_TIMEOUT = 10
SPECIAL = {
    "/stop", "/pause", "/resume", "/status", "/sessions",
    "/help", "/arm", "/disarm", "/close",
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# session record helpers
# --------------------------------------------------------------------------


def _read_session(sid: str) -> dict | None:
    f = paths.session_file(sid)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write_session(sid: str, rec: dict) -> None:
    tmp = paths.session_file(sid).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=2) + "\n")
    tmp.replace(paths.session_file(sid))


def _sid_for_thread(thread_id: int) -> str | None:
    f = paths.thread_file(thread_id)
    if not f.exists():
        return None
    return f.read_text().strip() or None


@contextlib.contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    with open(lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _append_inbox(sid: str, item: dict) -> None:
    f = paths.inbox_file(sid)
    with _locked(f), f.open("a") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def _forget_session(sid: str, thread_id: int | None) -> None:
    """Wipe all local state for a session. Does NOT delete the Telegram topic."""
    for p in (
        paths.session_file(sid),
        paths.inbox_file(sid),
        paths.inbox_file(sid).with_name(paths.inbox_file(sid).name + ".lock"),
        paths.counter_file(sid),
        paths.REGISTER / f"{sid}.json",
        paths.END / f"{sid}.json",
    ):
        p.unlink(missing_ok=True)
    if thread_id is not None:
        paths.thread_file(thread_id).unlink(missing_ok=True)
    outdir = paths.outbox_dir(sid)
    if outdir.exists():
        for f in outdir.iterdir():
            f.unlink(missing_ok=True)
        outdir.rmdir()


# --------------------------------------------------------------------------
# broker
# --------------------------------------------------------------------------


class Broker:
    def __init__(self, cfg: Config) -> None:
        cfg.validate()
        self.cfg = cfg
        self.tg = Telegram(cfg.bot_token, timeout=POLL_TIMEOUT + 15)
        self._running = True

    # --- lifecycle ---------------------------------------------------

    def run(self) -> None:
        paths.ensure_dirs()
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)
        self._init_offset()
        log.info("broker up (chat_id=%s, offset=%s)", self.cfg.chat_id, self._offset)
        while self._running:
            try:
                self._process_registrations()
                self._process_outbox()   # deliver responses before any "ended" notice
                self._process_end()
                self._process_updates()  # long-poll (POLL_TIMEOUT) sits here
            except TelegramError as e:
                log.warning("telegram error: %s", e)
                time.sleep(3)
            except Exception:
                log.exception("unexpected error in main loop")
                time.sleep(3)
        self.tg.close()
        log.info("broker stopped")

    def _stop(self, *_: object) -> None:
        log.info("signal received, shutting down")
        self._running = False

    # --- offset ---------------------------------------------------

    def _init_offset(self) -> None:
        if paths.OFFSET_FILE.exists():
            self._offset = int(paths.OFFSET_FILE.read_text().strip() or "0")
            return
        # First run: fast-forward past any backlog so we don't replay old chatter.
        try:
            updates = self.tg.get_updates(offset=-1, timeout=0)
        except TelegramError:
            updates = []
        self._offset = (updates[-1]["update_id"] + 1) if updates else 0
        self._save_offset()

    def _save_offset(self) -> None:
        paths.OFFSET_FILE.write_text(str(self._offset))

    # --- registrations -> topics -----------------------------------

    def _process_registrations(self) -> None:
        for f in sorted(paths.REGISTER.glob("*.json")):
            try:
                req = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                f.unlink(missing_ok=True)
                continue
            sid = req.get("session_id") or f.stem
            if _read_session(sid):
                f.unlink(missing_ok=True)  # already registered
                continue
            label = req.get("label") or sid[:12]
            cwd = req.get("cwd", "?")
            try:
                thread_id = self.tg.create_forum_topic(self.cfg.chat_id, label)
            except TelegramError as e:
                log.error("createForumTopic failed for %s: %s", sid, e)
                send_with_retry(
                    self.tg,
                    self.cfg.chat_id,
                    f"⚠️ could not create topic for session {label} ({sid}): {e}",
                )
                f.unlink(missing_ok=True)
                continue
            rec = {
                "session_id": sid,
                "label": label,
                "cwd": cwd,
                "thread_id": thread_id,
                "status": "active",
                "paused": False,
                "started": _now(),
            }
            _write_session(sid, rec)
            paths.thread_file(thread_id).write_text(sid)
            f.unlink(missing_ok=True)
            header = (
                f"🟢 session {label}\n"
                f"cwd: {cwd}\n"
                f"id: {sid}\n"
                f"started: {rec['started']}\n\n"
                "Reply in this topic to send a command "
                "(the first one arms the session).\n"
                "/status  /arm  /disarm  /pause  /resume  /stop"
            )
            send_with_retry(self.tg, self.cfg.chat_id, header, message_thread_id=thread_id)
            log.info("registered %s -> topic %s", label, thread_id)

    # --- inbound updates -> inbox ---------------------------------

    def _process_updates(self) -> None:
        updates = self.tg.get_updates(offset=self._offset, timeout=POLL_TIMEOUT)
        for upd in updates:
            self._offset = upd["update_id"] + 1
            msg = upd.get("message")
            if msg:
                try:
                    self._handle_message(msg)
                except Exception:
                    log.exception("failed handling update %s", upd.get("update_id"))
            self._save_offset()  # per-update so a crash never replays a command

    def _handle_message(self, msg: dict) -> None:
        text = msg.get("text")
        if not text or not text.strip():
            return  # service message, media without caption, whitespace, etc.
        thread_id = msg.get("message_thread_id")
        if thread_id is None:
            self._reply_general(msg)
            return
        sid = _sid_for_thread(thread_id)
        if not sid:
            return  # a topic we don't manage

        rec = _read_session(sid)
        if not rec:
            return

        cmd = text.strip()
        if cmd.split()[0] in SPECIAL:
            self._handle_special(sid, rec, thread_id, cmd)
            return

        if rec.get("status") == "ended":
            self._say(thread_id, "session has ended — command ignored.")
            return

        _append_inbox(sid, {"text": text, "update_id": msg.get("message_id"), "ts": _now()})
        if not rec.get("armed"):
            rec["armed"] = True
            _write_session(sid, rec)
        log.info("queued command for %s (%d chars)", rec["label"], len(text))

    def _handle_special(self, sid: str, rec: dict, thread_id: int, cmd: str) -> None:
        head = cmd.split()[0]
        if head == "/help":
            self._say(
                thread_id,
                "/status   show state\n"
                "/arm      wait full poll window for commands\n"
                "/disarm   only glance briefly (frees the terminal)\n"
                "/pause    hold commands until /resume\n"
                "/resume   deliver held commands\n"
                "/stop     stop injecting into this session\n"
                "/close    stop, then delete this topic",
            )
        elif head == "/status":
            n = _inbox_len(sid)
            self._say(
                thread_id,
                f"label: {rec['label']}\nstatus: {rec['status']}"
                f"\narmed: {rec.get('armed', False)}\npaused: {rec.get('paused', False)}"
                f"\nqueued commands: {n}\ncwd: {rec['cwd']}",
            )
        elif head == "/arm":
            rec["armed"] = True
            _write_session(sid, rec)
            self._say(thread_id, "🎯 armed — Stop hook will wait the full poll window for commands.")
        elif head == "/disarm":
            rec["armed"] = False
            _write_session(sid, rec)
            self._say(thread_id, "💤 disarmed — Stop hook will only glance briefly; terminal stays responsive.")
        elif head == "/sessions":
            self._say(thread_id, _sessions_summary())
        elif head == "/pause":
            rec["paused"] = True
            _write_session(sid, rec)
            self._say(thread_id, "⏸ paused — commands will queue until /resume.")
        elif head == "/resume":
            rec["paused"] = False
            _write_session(sid, rec)
            self._say(thread_id, f"▶️ resumed — {_inbox_len(sid)} queued command(s) will be delivered.")
        elif head == "/stop":
            rec["status"] = "ended"
            _write_session(sid, rec)
            # tell the hook to stop waiting
            _append_inbox(sid, {"control": "stop", "ts": _now()})
            self._say(thread_id, "🛑 stop signalled — the session will not receive further commands.")
        elif head == "/close":
            _append_inbox(sid, {"control": "stop", "ts": _now()})
            deleted = self.tg.delete_forum_topic(self.cfg.chat_id, thread_id)
            _forget_session(sid, thread_id)
            if not deleted:
                # topic couldn't be deleted (e.g. it's the General topic); say so
                self._say(thread_id, "stopped; could not delete this topic — remove it manually.")
            log.info("closed session %s (topic %s, deleted=%s)", rec["label"], thread_id, deleted)

    def _reply_general(self, msg: dict) -> None:
        chat_id = msg["chat"]["id"]
        self.tg.send_message(
            chat_id,
            "Send commands inside a session's topic, not here.",
        )

    # --- outbox -> telegram --------------------------------------

    def _process_outbox(self) -> None:
        if not paths.OUTBOX.exists():
            return
        for sdir in sorted(paths.OUTBOX.iterdir()):
            if not sdir.is_dir():
                continue
            sid = sdir.name
            rec = _read_session(sid)
            thread_id = rec["thread_id"] if rec else None
            for f in sorted(sdir.glob("*.txt")):
                text = f.read_text()
                ok = send_with_retry(
                    self.tg, self.cfg.chat_id, text, message_thread_id=thread_id
                )
                if ok:
                    f.unlink(missing_ok=True)
                else:
                    log.warning("failed to send outbox %s, will retry", f)
                    break

    # --- end -> cleanup ----------------------------------------

    def _process_end(self) -> None:
        for f in sorted(paths.END.glob("*.json")):
            sid = f.stem
            rec = _read_session(sid)
            if rec:
                rec["status"] = "ended"
                rec["ended"] = _now()
                _write_session(sid, rec)
                if rec.get("thread_id"):
                    self._say(rec["thread_id"], "🔴 session ended.")
            f.unlink(missing_ok=True)
            log.info("session %s ended", sid)

    # --- small helpers ---------------------------------------

    def _say(self, thread_id: int, text: str) -> None:
        send_with_retry(self.tg, self.cfg.chat_id, text, message_thread_id=thread_id)


def _inbox_len(sid: str) -> int:
    f = paths.inbox_file(sid)
    if not f.exists():
        return 0
    return sum(1 for line in f.read_text().splitlines() if line.strip())


def _sessions_summary() -> str:
    rows = []
    for f in sorted(paths.SESSIONS.glob("*.json")):
        try:
            r = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        rows.append(f"{r['label']:<24} {r['status']:<8} q={_inbox_len(r['session_id'])}")
    return "\n".join(rows) if rows else "(no sessions)"


# --------------------------------------------------------------------------
# entry point used by the CLI
# --------------------------------------------------------------------------


def _setup_logging(foreground: bool) -> None:
    paths.ensure_dirs()
    handlers: list[logging.Handler] = [logging.FileHandler(paths.LOG_FILE)]
    if foreground:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main(foreground: bool = True) -> None:
    _setup_logging(foreground)
    if paths.PID_FILE.exists():
        old = paths.PID_FILE.read_text().strip()
        if old and old.isdigit() and _alive(int(old)):
            raise SystemExit(f"broker already running (pid {old})")
    paths.PID_FILE.write_text(str(os.getpid()))
    try:
        Broker(Config.load()).run()
    finally:
        paths.PID_FILE.unlink(missing_ok=True)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return isinstance(sys.exc_info()[1], PermissionError)
    return True


if __name__ == "__main__":
    # spawned by `bridge start` with stdout/stderr already pointed at the log file
    main(foreground=False)
