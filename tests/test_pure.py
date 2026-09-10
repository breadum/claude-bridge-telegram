"""Pure helpers with no I/O."""

from __future__ import annotations

from claude_bridge_telegram.broker import _format_outbox, _read_outbox_item


def test_format_outbox_prefixes():
    assert _format_outbox("user", "hi").startswith("🧑")
    assert _format_outbox("assistant", "hi").startswith("🤖")
    assert _format_outbox("note", "hi").startswith("⚠️")
    assert _format_outbox("weird", "hi") == "hi"


def test_format_outbox_empty():
    assert _format_outbox("assistant", "   ") == "🤖 (empty)"
    assert _format_outbox("weird", "   ") == "(empty)"


def test_read_outbox_item_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"role": "user", "text": "hello"}')
    assert _read_outbox_item(p) == ("user", "hello", "")


def test_read_outbox_item_json_with_ai_title(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"role": "assistant", "text": "done", "ai_title": "Fix login flow"}')
    assert _read_outbox_item(p) == ("assistant", "done", "Fix login flow")


def test_read_outbox_item_legacy_txt(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("plain response")
    assert _read_outbox_item(p) == ("assistant", "plain response", "")
