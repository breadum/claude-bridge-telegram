"""Pure helpers with no I/O."""

from __future__ import annotations

from claude_bridge_telegram.broker import _format_outbox, _read_outbox_item, _topic_title


def test_topic_title_short_passthrough():
    assert _topic_title("myapp", "fix login bug") == "myapp: fix login bug"


def test_topic_title_no_base():
    assert _topic_title("", "hello world") == "hello world"


def test_topic_title_cuts_long_at_clause_break():
    long = "the button is broken when I click it twice, and also the modal never closes properly afterwards"
    out = _topic_title("web", long)
    assert out.startswith("web: the button is broken when I click it twice")
    assert "," not in out.split(": ", 1)[1]


def test_topic_title_hard_truncates_when_no_break():
    long = "x" * 200
    out = _topic_title("d", long)
    assert len(out) <= 128
    assert out.endswith("…")


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
    assert _read_outbox_item(p) == ("user", "hello")


def test_read_outbox_item_legacy_txt(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("plain response")
    assert _read_outbox_item(p) == ("assistant", "plain response")
