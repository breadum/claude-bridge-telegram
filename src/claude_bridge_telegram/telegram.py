"""Minimal Telegram Bot API client (only the handful of methods the bridge needs)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from .render import strip_tags

API_BASE = "https://api.telegram.org"
MESSAGE_LIMIT = 4096


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token: str, *, timeout: float = 40.0) -> None:
        self._base = f"{API_BASE}/bot{token}"
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Telegram:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _call(self, method: str, **params: Any) -> Any:
        payload = {k: v for k, v in params.items() if v is not None}
        resp = self._client.post(f"{self._base}/{method}", json=payload)
        try:
            data = resp.json()
        except ValueError:
            raise TelegramError(f"{method}: non-JSON response {resp.status_code}: {resp.text[:200]}")
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('error_code')} {data.get('description')}")
        return data["result"]

    # --- setup / introspection ---------------------------------------------

    def get_me(self) -> dict:
        return self._call("getMe")

    def get_chat(self, chat_id: int) -> dict:
        return self._call("getChat", chat_id=chat_id)

    # --- polling ----------------------------------------------------------

    def get_updates(self, offset: int, *, timeout: int = 30) -> list[dict]:
        # allowed_updates=["message"] : we only care about topic messages.
        return self._call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            allowed_updates=["message"],
        )

    # --- output ---------------------------------------------------------

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        message_thread_id: int | None = None,
        parse_mode: str | None = None,
    ) -> None:
        for chunk in _split(text, MESSAGE_LIMIT):
            try:
                self._call(
                    "sendMessage",
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    text=chunk,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )
            except TelegramError as e:
                # A chunk that split mid-tag (or a converter bug) makes Telegram
                # reject the markup — resend it flat so nothing is lost.
                if parse_mode and _is_markup_error(e):
                    self._call(
                        "sendMessage",
                        chat_id=chat_id,
                        message_thread_id=message_thread_id,
                        text=strip_tags(chunk),
                        disable_web_page_preview=True,
                    )
                else:
                    raise

    # --- forum topics --------------------------------------------------

    def create_forum_topic(self, chat_id: int, name: str) -> int:
        res = self._call("createForumTopic", chat_id=chat_id, name=name[:128])
        return int(res["message_thread_id"])

    def edit_forum_topic(self, chat_id: int, message_thread_id: int, name: str) -> bool:
        """Rename a topic. Returns False if it failed (gone / no rights)."""
        try:
            self._call(
                "editForumTopic",
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                name=name[:128],
            )
            return True
        except TelegramError:
            return False

    def close_forum_topic(self, chat_id: int, message_thread_id: int) -> None:
        try:
            self._call(
                "closeForumTopic",
                chat_id=chat_id,
                message_thread_id=message_thread_id,
            )
        except TelegramError:
            pass

    def delete_forum_topic(self, chat_id: int, message_thread_id: int) -> bool:
        """Delete a topic and all its messages. Returns False if it was already
        gone or we lack rights."""
        try:
            self._call(
                "deleteForumTopic",
                chat_id=chat_id,
                message_thread_id=message_thread_id,
            )
            return True
        except TelegramError:
            return False


def _is_markup_error(e: TelegramError) -> bool:
    m = str(e).lower()
    return "parse" in m or "entities" in m or "tag" in m or "entity" in m


def _split(text: str, limit: int) -> list[str]:
    text = text if text.strip() else "(empty response)"
    if len(text) <= limit:
        return [text]
    out: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        out.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        out.append(remaining)
    return out


def send_with_retry(
    tg: Telegram,
    chat_id: int,
    text: str,
    *,
    message_thread_id: int | None = None,
    parse_mode: str | None = None,
    attempts: int = 4,
) -> bool:
    """Best-effort send; returns True on success. Used by the broker so a
    transient failure doesn't drop an outbox file."""
    for i in range(attempts):
        try:
            tg.send_message(
                chat_id, text, message_thread_id=message_thread_id, parse_mode=parse_mode
            )
            return True
        except TelegramError:
            if i == attempts - 1:
                return False
            time.sleep(2 ** i)
    return False
