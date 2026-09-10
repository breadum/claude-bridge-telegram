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
    assert any("proj" in t for _, t, _ in fake.sent)  # header sent to topic
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
    assert any("재시도" in t for _, t, _ in fake.sent)

    # now the socket comes back; retry drains the queue
    ok = []
    monkeypatch.setattr(broker, "inject_user_message", lambda s, t, text: ok.append(text))
    b._process_inbox()
    assert ok == ["later"]
    assert paths.inbox_file("s1").read_text().strip() == ""


def test_slash_stop_marks_ended_and_clears_queue(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    broker._inbox_append("s1", "queued")

    b._handle_message({"message_thread_id": 101, "text": "/stop"})
    rec = json.loads(paths.session_file("s1").read_text())
    assert rec["status"] == "ended"
    assert paths.inbox_file("s1").read_text().strip() == ""


def test_slash_close_deletes_topic_and_state(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()

    b._handle_message({"message_thread_id": 101, "text": "/close"})
    assert fake.deleted == [(-1001, 101)]
    assert not paths.session_file("s1").exists()
    assert not paths.thread_file(101).exists()


def test_message_to_ended_session_is_ignored(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    b._handle_message({"message_thread_id": 101, "text": "/stop"})
    fake.sent.clear()

    monkeypatch.setattr(broker, "inject_user_message", lambda *a: (_ for _ in ()).throw(AssertionError("injected!")))
    b._handle_message({"message_thread_id": 101, "text": "hello?"})
    assert any("ended" in t for _, t, _ in fake.sent)


def test_outbox_titles_topic_from_first_user_message(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    fake.edited.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    (d / "001.json").write_text(json.dumps({"role": "user", "text": "fix the flaky login test"}))
    b._process_outbox()

    assert fake.edited and "fix the flaky login test" in fake.edited[0][2]
    rec = json.loads(paths.session_file("s1").read_text())
    assert rec["titled"] is True
