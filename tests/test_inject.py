"""The [uds-messaging] socket client."""

from __future__ import annotations

import json
import socket
import threading

import pytest

from claude_bridge_telegram.inject import InjectError, inject_user_message


class _Server:
    """Minimal AF_UNIX server: accept one client, read newline frames."""

    def __init__(self, path: str) -> None:
        self.frames: list[dict] = []
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(path)
        self._sock.listen(1)
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    def _serve(self) -> None:
        conn, _ = self._sock.accept()
        buf = b""
        conn.settimeout(2.0)
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        self.frames.append(json.loads(line))
        except OSError:
            pass
        finally:
            conn.close()
            self._sock.close()

    def join(self) -> None:
        self._t.join(timeout=3)


def test_inject_sends_auth_then_user_frame(tmp_path):
    path = str(tmp_path / "s.sock")
    srv = _Server(path)
    inject_user_message(path, "mytoken", "run the tests")
    srv.join()
    assert srv.frames[0] == {"type": "auth", "token": "mytoken"}
    assert srv.frames[1] == {
        "type": "user",
        "message": {"role": "user", "content": "run the tests"},
    }


def test_inject_missing_socket_raises(tmp_path):
    with pytest.raises(InjectError):
        inject_user_message(str(tmp_path / "gone.sock"), "t", "hi")


def test_inject_requires_socket_and_token():
    with pytest.raises(InjectError):
        inject_user_message("", "t", "hi")
    with pytest.raises(InjectError):
        inject_user_message("/x", "", "hi")
