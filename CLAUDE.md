# CLAUDE.md — working rules for this repo

Guidance for anyone (human or Claude Code) changing `claude-bridge-telegram`.
Read this before editing. It records the invariants that are easy to break.

## What this is

A bridge between Claude Code sessions and a Telegram forum group: one **topic
per session**, prompts + responses mirrored out, and Telegram messages injected
back into the running session. No web service, no database — a single broker
daemon plus four Claude Code hooks talking through files.

## Architecture (do not break these)

1. **Hooks are stdlib-only and non-blocking.** Everything in `hooks/` runs from
   `~/.claude/settings.json` with the *system* `python3` on every session event.
   - No third-party imports. No `import claude_bridge_telegram`. `_bridge_common.py`
     is a deliberate standalone mirror of `paths.py` — keep them in sync by hand;
     do not merge them.
   - A hook writes one small file under `paths.ROOT` and calls `bc.emit()`. It
     must never block, poll, or wait. (The old `Stop` hook blocked for minutes;
     that is gone and must not come back.)

2. **The broker is the only thing that talks to Telegram.** It owns the
   `getUpdates` offset, so nothing else may call the Bot API — concurrent
   sessions would race the offset.

3. **Telegram → session goes over Claude Code's `[uds-messaging]` socket**, not a
   hook. `session_start.py` records `CLAUDE_CODE_MESSAGING_SOCKET` +
   `CLAUDE_CODE_MESSAGING_TOKEN` (inherited from the `claude` parent) into the
   register file; `inject.py` connects to that socket, sends an `auth` frame then
   a `user` frame. This works whether the session is idle or mid-turn.
   - The session receives it as a **peer message**, not a first-person user
     prompt. Two setup requirements follow (neither is a bug to fix in the bridge):
     1. `~/.claude/settings.json` must set `"crossSessionInbound": "accept"`.
        Otherwise Claude Code *holds* peer messages from an unattested sender
        when the receiving session bypasses prompts — the socket write succeeds
        but the message never reaches the model (it lands in the transcript as a
        "Held peer message" system notice).
     2. Telegram-driven sessions must run with `--dangerously-skip-permissions`
        (or an equivalent trusted mode). A peer message will *not* dismiss a
        native tool-permission dialog.

4. **File-queue contract between hook and broker:**
   - `register/<sid>.json` — session_start → broker makes/refreshes a topic
   - `sessions/<sid>.json` — broker's record (label, thread_id, socket, token, status, titled)
   - `outbox/<sid>/<ts>.json` — `{"role": "user"|"assistant"|"note", "text": ...}`,
     optional `"ai_title"` (Claude Code's own session title, forwarded by the
     `Stop` hook — the broker renames the topic to it once) → broker sends to the topic
   - `inbox/<sid>.jsonl` — commands that *failed* to inject, retried each loop
   - `end/<sid>.json` — session_end → broker marks ended / deletes topic
   Change the `outbox` JSON shape and you must change both the hook that writes
   it (`_bridge_common.queue_outbox`) and `broker._read_outbox_item`.

5. **Mirrored message bodies go out as Telegram HTML.** `render.to_telegram_html`
   maps Claude's Markdown onto Telegram's tag subset; `_process_outbox` sends it
   with `parse_mode="HTML"`. `telegram.send_message` retries a chunk tag-stripped
   if Telegram rejects the markup, so a converter bug un-styles a message but
   never drops it. The bridge's *own* messages (`_say`, topic header) stay plain
   — don't pass `parse_mode` for those unless you also escape them.

6. **`UserPromptSubmit` also fires for machine turns** — a finished background
   task, a locally-run slash command, injected context blocks. `render.tidy_prompt`
   (called in `_process_outbox` for `role == "user"`) rewrites the ones worth
   showing into a one-line `event` (🔔) and returns `None` for pure noise, which
   the broker then drops. Add a pattern there, not in the hook.

## Secrets

- The Telegram bot token lives **only** in `~/.claude/bridge/config.json`
  (chmod 600), written by `bridge setup`. It is never in the repo.
- `messaging_token` is a per-session Claude Code secret. It is written into
  `sessions/` / `register/` (runtime dir, git-ignored). Never log it, never
  print it, never commit a fixture containing a real one.
- Before every commit, scan for the token: `git grep -i "$(printf %s '8713')"` /
  a plain `grep -rn` for the known value. Zero hits required.

## Dev workflow

```bash
uv sync
uv run ruff check .
uv run pytest
```

- Line length 100, target py312, `from __future__ import annotations` at the top
  of every module.
- Tests must not hit the network or the real `~/.claude`. `tests/conftest.py`
  points `CLAUDE_TG_BRIDGE_HOME` at a temp dir before collection; use
  `tests/fakes.py::FakeTelegram` and a stubbed `broker.inject_user_message`.
- Hooks are exercised as real subprocesses (`tests/test_hooks.py`) — that is how
  Claude Code runs them, so keep it that way.

## Commits

- Short imperative subject. Body explains *why* when it isn't obvious.
- End every commit message with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  ```
- Don't commit to `main` directly; branch and open a PR.

## Running as a service

`service/claude-bridge-telegram.service.in` is a template; `service/install.sh`
renders `@REPO_DIR@` / `@BRIDGE_BIN@` from its own location, so the checkout can
live anywhere. After moving the repo: `uv sync`, `bridge install-hooks`,
`./service/install.sh` again.
