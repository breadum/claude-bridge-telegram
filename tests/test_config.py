"""Config load/save/validate."""

from __future__ import annotations

import stat

import pytest

from claude_bridge_telegram.config import Config


def test_defaults():
    c = Config()
    assert c.bot_token == ""
    assert c.chat_id == 0
    assert c.delete_topic_on_end is False


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("CLAUDE_TG_BOT_TOKEN", "abc123")
    monkeypatch.setenv("CLAUDE_TG_CHAT_ID", "-1009999")
    monkeypatch.setenv("CLAUDE_TG_DELETE_TOPIC_ON_END", "true")
    c = Config.load()
    assert c.bot_token == "abc123"
    assert c.chat_id == -1009999
    assert c.delete_topic_on_end is True


def test_save_roundtrip_and_perms(bridge_home):
    c = Config(bot_token="s3cr3t", chat_id=-100123)
    c.save()
    from claude_bridge_telegram.config import CONFIG_FILE

    assert CONFIG_FILE.exists()
    mode = stat.S_IMODE(CONFIG_FILE.stat().st_mode)
    assert mode == 0o600
    loaded = Config.load()
    assert loaded.bot_token == "s3cr3t"
    assert loaded.chat_id == -100123


def test_validate_requires_token_and_chat():
    with pytest.raises(SystemExit):
        Config(bot_token="", chat_id=-1).validate()
    with pytest.raises(SystemExit):
        Config(bot_token="x", chat_id=0).validate()
    Config(bot_token="x", chat_id=-1).validate()  # ok, no raise
