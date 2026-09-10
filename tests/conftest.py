"""Test setup: isolate every test from the real ~/.claude/bridge.

This file runs before any test module is imported, so setting
CLAUDE_TG_BRIDGE_HOME here means `claude_bridge_telegram.paths` and the hook
scripts resolve their ROOT to a throwaway directory.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TMP_HOME = Path(tempfile.mkdtemp(prefix="bridge-test-home-"))

os.environ["CLAUDE_TG_BRIDGE_HOME"] = str(_TMP_HOME)
# hooks import `_bridge_common` by bare name
sys.path.insert(0, str(_REPO / "hooks"))

import pytest


def pytest_unconfigure(config):
    shutil.rmtree(_TMP_HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def bridge_home() -> Path:
    """A clean ~/.claude/bridge for every test."""
    from claude_bridge_telegram import paths

    for child in _TMP_HOME.iterdir():
        shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
    paths.ensure_dirs()
    return _TMP_HOME


@pytest.fixture
def hook_env() -> dict[str, str]:
    """Environment for running a hook script as a subprocess."""
    env = dict(os.environ)
    env["CLAUDE_TG_BRIDGE_HOME"] = str(_TMP_HOME)
    return env


def transcript(path: Path, turns: list[tuple[str, str]]) -> Path:
    """Write a minimal Claude Code transcript .jsonl. turns = [(role, text), ...]."""
    import json

    lines = []
    for role, text in turns:
        lines.append(
            json.dumps(
                {"type": role, "message": {"role": role, "content": [{"type": "text", "text": text}]}}
            )
        )
    path.write_text("\n".join(lines) + "\n")
    return path
