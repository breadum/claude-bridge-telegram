"""Bridge configuration.

Written by `bridge setup` to <ROOT>/config.json. Env vars override individual
fields (handy for testing): CLAUDE_TG_BOT_TOKEN, CLAUDE_TG_CHAT_ID,
CLAUDE_TG_DELETE_TOPIC_ON_END, ANTHROPIC_API_KEY, CLAUDE_TG_TITLE_MODEL.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from . import paths

CONFIG_FILE: Path = paths.ROOT / "config.json"


@dataclass
class Config:
    bot_token: str = ""
    chat_id: int = 0
    # When true, ending a session (SessionEnd / normal /exit) also deletes its
    # Telegram topic. Default: keep the topic (delete it later with /close or
    # `bridge prune`).
    delete_topic_on_end: bool = False
    # Optional: with an Anthropic API key, the topic title is an LLM summary of
    # the first prompt instead of a truncation. Falls back silently without a key.
    anthropic_api_key: str = ""
    title_model: str = "claude-haiku-4-5-20251001"

    @classmethod
    def load(cls) -> Config:
        data: dict = {}
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text())
        cfg = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

        if v := os.environ.get("CLAUDE_TG_BOT_TOKEN"):
            cfg.bot_token = v
        if v := os.environ.get("CLAUDE_TG_CHAT_ID"):
            cfg.chat_id = int(v)
        if v := os.environ.get("CLAUDE_TG_DELETE_TOPIC_ON_END"):
            cfg.delete_topic_on_end = v.lower() in ("1", "true", "yes")
        if v := os.environ.get("ANTHROPIC_API_KEY"):
            cfg.anthropic_api_key = v
        if v := os.environ.get("CLAUDE_TG_TITLE_MODEL"):
            cfg.title_model = v
        return cfg

    def save(self) -> None:
        paths.ROOT.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2) + "\n")
        CONFIG_FILE.chmod(0o600)

    def validate(self) -> None:
        if not self.bot_token:
            raise SystemExit("no bot_token configured — run `bridge setup`")
        if not self.chat_id:
            raise SystemExit("no chat_id configured — run `bridge setup`")
