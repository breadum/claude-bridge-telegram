"""Inject a message into a running Claude Code session.

Claude Code 2.x listens on a per-session Unix socket (its ``[uds-messaging]``
inbox) at ``$CLAUDE_CODE_MESSAGING_SOCKET`` — ``$XDG_RUNTIME_DIR/cc-socks/<pid>.sock``.
A client authenticates with ``$CLAUDE_CODE_MESSAGING_TOKEN`` and then writes
newline-delimited JSON frames. A ``user`` frame is routed into the session's
prompt queue whether the session is mid-turn or idle — which is exactly how the
bridge delivers a Telegram message to the session, with no blocking hook.

The session receives it as a *peer* message (same channel used between local
Claude sessions), not a first-person user prompt: it will not dismiss a native
tool-permission prompt. Sessions driven from Telegram should run with
``--dangerously-skip-permissions`` (or an equivalent trusted permission mode).
"""

from __future__ import annotations

import json
import socket


class InjectError(Exception):
    """The session socket was missing, unreachable, or refused the frame."""


def inject_user_message(
    sock_path: str,
    token: str,
    text: str,
    *,
    timeout: float = 3.0,
) -> None:
    """Send one ``user`` message to the session listening on ``sock_path``.

    Raises :class:`InjectError` if the socket is gone (session exited/restarted)
    or the write fails. Returns None on success. The server sends no reply on
    this connection, so success means "written and accepted without error".
    """
    if not sock_path or not token:
        raise InjectError("missing socket path or token for this session")

    auth = json.dumps({"type": "auth", "token": token})
    frame = json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}}
    )

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(sock_path)
        s.sendall(auth.encode() + b"\n")
        s.sendall(frame.encode() + b"\n")
        # Let the server consume the frames before we tear the connection down.
        s.shutdown(socket.SHUT_WR)
        try:
            while s.recv(4096):
                pass
        except OSError:
            pass
    except OSError as e:
        raise InjectError(f"{sock_path}: {e}") from e
    finally:
        s.close()
