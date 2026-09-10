"""Hook-side stdlib helpers."""

from __future__ import annotations

import json

import _bridge_common as bc
from conftest import transcript


def test_queue_outbox_writes_role_and_text():
    bc.queue_outbox("sid1", "user", "안녕하세요")
    files = list((bc.OUTBOX / "sid1").iterdir())
    assert len(files) == 1
    obj = json.loads(files[0].read_text())
    assert obj == {"role": "user", "text": "안녕하세요"}


def test_last_assistant_text_takes_final_assistant(tmp_path):
    t = transcript(
        tmp_path / "t.jsonl",
        [("user", "hi"), ("assistant", "first"), ("user", "more"), ("assistant", "final answer")],
    )
    assert bc.last_assistant_text(str(t)) == "final answer"


def test_last_assistant_text_missing_file():
    assert bc.last_assistant_text("/no/such/file") == "(transcript unavailable)"


def test_write_json_atomic_roundtrip(tmp_path):
    p = tmp_path / "d" / "x.json"
    bc.write_json_atomic(p, {"a": 1, "ko": "값"})
    assert bc.read_json(p) == {"a": 1, "ko": "값"}
    assert not p.with_name(p.name + ".tmp").exists()


def test_ts_is_sortable():
    a = bc.ts()
    b = bc.ts()
    assert a <= b
    assert "T" in a
