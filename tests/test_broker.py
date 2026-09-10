"""Broker loop steps, with a fake Telegram and a stubbed injector."""

from __future__ import annotations

import json

import fakes

from claude_bridge_telegram import broker, paths


def _register(sid="s1", socket="/run/cc-socks/9.sock", token="tok9"):
    paths.ensure_dirs()
    (paths.REGISTER / f"{sid}.json").write_text(json.dumps({
        "session_id": sid, "label": f"proj-{sid}", "base": "proj", "cwd": "/w/proj",
        "messaging_socket": socket, "messaging_token": token, "pid": "9",
    }))


def test_registration_creates_topic(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()

    rec = json.loads(paths.session_file("s1").read_text())
    assert rec["thread_id"] == 101
    assert rec["messaging_socket"] == "/run/cc-socks/9.sock"
    assert rec["status"] == "active"
    assert paths.thread_file(101).read_text() == "s1"
    assert fake.created == [(-1001, "proj …")]
    assert any("proj" in t for _, t, *_ in fake.sent)  # header sent to topic
    assert not (paths.REGISTER / "s1.json").exists()


def test_registration_refreshes_socket_on_resume(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    assert len(fake.created) == 1

    # resume: same sid, new pid/socket
    _register(socket="/run/cc-socks/77.sock", token="tok77")
    b._process_registrations()

    rec = json.loads(paths.session_file("s1").read_text())
    assert rec["messaging_socket"] == "/run/cc-socks/77.sock"
    assert rec["messaging_token"] == "tok77"
    assert len(fake.created) == 1  # no second topic


def test_topic_message_is_injected(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()

    calls = []
    monkeypatch.setattr(broker, "inject_user_message", lambda s, t, text: calls.append((s, t, text)))

    b._handle_message({"message_thread_id": 101, "text": "run the build"})
    assert calls == [("/run/cc-socks/9.sock", "tok9", "run the build")]


def test_failed_injection_is_queued_for_retry(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()

    def boom(*a):
        raise broker.InjectError("no socket")

    monkeypatch.setattr(broker, "inject_user_message", boom)
    b._handle_message({"message_thread_id": 101, "text": "later"})

    lines = paths.inbox_file("s1").read_text().splitlines()
    assert json.loads(lines[0])["text"] == "later"
    assert any("재시도" in t for _, t, *_ in fake.sent)

    # now the socket comes back; retry drains the queue
    ok = []
    monkeypatch.setattr(broker, "inject_user_message", lambda s, t, text: ok.append(text))
    b._process_inbox()
    assert ok == ["later"]
    assert paths.inbox_file("s1").read_text().strip() == ""


def test_slash_exit_deletes_topic_but_keeps_session_record(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    broker._inbox_append("s1", "queued")
    paths.outbox_dir("s1").mkdir(parents=True, exist_ok=True)
    (paths.outbox_dir("s1") / "x.json").write_text('{"role":"assistant","text":"hi"}')

    b._handle_message({"message_thread_id": 101, "text": "/exit"})

    assert fake.deleted == [(-1001, 101)]
    assert not paths.thread_file(101).exists()          # dead routing dropped
    assert paths.inbox_file("s1").read_text().strip() == ""
    assert not paths.outbox_dir("s1").exists()          # mirror queue wiped
    rec = json.loads(paths.session_file("s1").read_text())  # record kept
    assert rec["status"] == "ended"


def test_exited_session_outbox_is_dropped_not_retried(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    b._handle_message({"message_thread_id": 101, "text": "/exit"})
    fake.sent.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    (d / "late.json").write_text('{"role":"assistant","text":"late reply"}')
    b._process_outbox()
    assert fake.sent == []
    assert not d.exists()


def test_resume_after_exit_gets_a_fresh_topic(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    b._handle_message({"message_thread_id": 101, "text": "/exit"})

    _register()  # SessionStart fires again on resume
    b._process_registrations()

    assert len(fake.created) == 2                       # a new topic, not reused
    rec = json.loads(paths.session_file("s1").read_text())
    assert rec["status"] == "active"
    assert rec["thread_id"] == 102


def test_message_to_ended_session_is_ignored(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    # mark ended without deleting the topic (SessionEnd, delete_topic_on_end off)
    rec = json.loads(paths.session_file("s1").read_text())
    rec["status"] = "ended"
    paths.session_file("s1").write_text(json.dumps(rec))
    fake.sent.clear()

    monkeypatch.setattr(broker, "inject_user_message", lambda *a: (_ for _ in ()).throw(AssertionError("injected!")))
    b._handle_message({"message_thread_id": 101, "text": "hello?"})
    assert any("ended" in t for _, t, *_ in fake.sent)


def test_outbox_titles_topic_from_ai_title(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    fake.edited.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    (d / "001.json").write_text(json.dumps(
        {"role": "assistant", "text": "done", "ai_title": "Fix the flaky login test"}
    ))
    b._process_outbox()

    assert fake.edited and fake.edited[0][2] == "Fix the flaky login test"
    rec = json.loads(paths.session_file("s1").read_text())
    assert rec["titled"] is True


def test_outbox_without_ai_title_does_not_rename(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    fake.edited.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    (d / "001.json").write_text(json.dumps({"role": "user", "text": "hello"}))
    b._process_outbox()

    assert fake.edited == []
    rec = json.loads(paths.session_file("s1").read_text())
    assert rec.get("titled") is False


def test_outbox_renders_markdown_as_html(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    fake.sent.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    (d / "001.json").write_text(json.dumps(
        {"role": "assistant", "text": "## Done\n\n**bold** and `code` and <raw>"}
    ))
    b._process_outbox()

    _, text, thread, parse_mode = fake.sent[-1]
    assert parse_mode == "HTML"
    assert text.startswith("🤖 ")
    assert "<b>Done</b>" in text
    assert "<b>bold</b>" in text
    assert "<code>code</code>" in text
    assert "&lt;raw&gt;" in text and "<raw>" not in text
    assert "##" not in text and "**" not in text


def test_outbox_tidies_task_notification(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    fake.sent.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    payload = (
        "<task-notification><status>completed</status>"
        '<summary>Background command "probe the fix" completed (exit code 0)</summary>'
        "</task-notification>"
    )
    (d / "001.json").write_text(json.dumps({"role": "user", "text": payload}))
    (d / "002.json").write_text(json.dumps(
        {"role": "user", "text": "<local-command-stdout></local-command-stdout>"}
    ))
    b._process_outbox()

    texts = [t for _, t, *_ in fake.sent]
    assert texts == ["🔔 probe the fix — completed (exit code 0)"]
    assert list(d.iterdir()) == []  # both consumed, the noise one silently
