"""A stand-in for the Telegram client. Records calls; touches no network."""

from __future__ import annotations


class FakeTelegram:
    def __init__(self, *args, **kwargs) -> None:
        self.sent: list[tuple[int, str, int | None]] = []
        self.created: list[tuple[int, str]] = []
        self.edited: list[tuple[int, int, str]] = []
        self.deleted: list[tuple[int, int]] = []
        self._next_thread = 100
        self.updates: list[dict] = []

    # --- outbound ---
    def send_message(self, chat_id: int, text: str, message_thread_id: int | None = None):
        self.sent.append((chat_id, text, message_thread_id))
        return {"message_id": len(self.sent)}

    def create_forum_topic(self, chat_id: int, name: str) -> int:
        self._next_thread += 1
        self.created.append((chat_id, name))
        return self._next_thread

    def edit_forum_topic(self, chat_id: int, message_thread_id: int, name: str) -> bool:
        self.edited.append((chat_id, message_thread_id, name))
        return True

    def delete_forum_topic(self, chat_id: int, message_thread_id: int) -> bool:
        self.deleted.append((chat_id, message_thread_id))
        return True

    def close_forum_topic(self, chat_id: int, message_thread_id: int) -> bool:
        return True

    # --- inbound ---
    def get_updates(self, offset: int, timeout: int = 30) -> list[dict]:
        out = [u for u in self.updates if u["update_id"] >= offset]
        self.updates = []
        return out

    def get_me(self) -> dict:
        return {"username": "fake_bot", "id": 1}

    def get_chat(self, chat_id: int) -> dict:
        return {"title": "Fake", "type": "supergroup", "is_forum": True}

    def close(self) -> None:
        pass


def install(monkeypatch, cfg_token: str = "tok", chat_id: int = -1001):
    """Patch broker.Telegram + send_with_retry, return (Broker, fake)."""
    from claude_bridge_telegram import broker
    from claude_bridge_telegram.config import Config

    fake = FakeTelegram()
    monkeypatch.setattr(broker, "Telegram", lambda *a, **k: fake)

    def _swr(tg, chat, text, message_thread_id=None, attempts=4):
        tg.send_message(chat, text, message_thread_id)
        return True

    monkeypatch.setattr(broker, "send_with_retry", _swr)

    b = broker.Broker(Config(bot_token=cfg_token, chat_id=chat_id))
    return b, fake
