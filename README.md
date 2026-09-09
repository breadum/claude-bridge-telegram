# claude-tg-bridge

Drive Claude Code sessions from Telegram. Each session gets its own **forum
topic** in a Telegram group: the session's responses stream into the topic, and
anything you type back in that topic is injected into the session as its next
instruction.

```
Claude Code session ──Stop hook──▶ outbox/<sid>/ ──▶ broker ──▶ Telegram topic
Telegram topic ──▶ broker (getUpdates) ──▶ inbox/<sid> ──Stop hook──▶ session
```

- **Hooks** (`hooks/*.py`, stdlib only) run on every `SessionStart` / `Stop` /
  `SessionEnd`. They only touch files under `~/.claude/bridge/`.
- **Broker** (`bridge` daemon) is the only process that talks to Telegram. It
  owns `getUpdates`, so multiple concurrent sessions never fight over the offset.

## Requirements

- Python 3.12 (pinned via `.python-version`, built with pyenv)
- [uv](https://docs.astral.sh/uv/) for the project venv
- A Telegram bot + a **supergroup with Topics enabled**

## 1. Create the Telegram bot & group

1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → copy the **token**.
2. Create a group. Open **group name → Edit → Topics** and turn it **on**, then
   save. The group must actually show a topic list / "General" topic afterwards —
   `getChat` must report `is_forum: true`.
3. **Add the bot to the group, then promote it to admin.** In the admin-rights
   screen you must explicitly enable **Manage Topics** (it is often off by
   default even for an admin). Being an admin also lets the bot see every
   message (bypasses privacy mode).
4. Send a message in the group **after** the bot is an admin — messages from
   before it joined / was promoted are never delivered to it.

If any of this is wrong you'll see it during `bridge setup` / in the broker log:
`is_forum: None`, `the chat is not a forum`, or `not enough rights to create a
topic`. See [Troubleshooting](#troubleshooting).

## 2. Install

```bash
cd ~/claude-tg-bridge
uv sync                      # create .venv from the lockfile
uv run bridge setup          # paste token, auto-detects the group chat id
uv run bridge start          # launch the broker daemon
uv run bridge install-hooks  # add hooks to ~/.claude/settings.json (backs it up)
```

Optionally put `bridge` on PATH: `uv tool install --editable ~/claude-tg-bridge`.

## 3. Use

Start a Claude Code session anywhere. A topic named like `myrepo-3f2a`
(`<cwd basename>-<session id prefix>`) appears in the group with a header line.

- The session's every reply shows up in that topic.
- Type a message in the topic → it becomes the session's next instruction.
- The **first** message you send *arms* the session (see below).

### Armed vs. un-armed

After each turn the `Stop` hook waits for a command before letting the session
go idle:

| state | wait | why |
|---|---|---|
| **un-armed** (default) | `grace_seconds` (5s) | so normal terminal use isn't blocked |
| **armed** | `poll_minutes` (5m) | so you can drive it entirely from Telegram |

Sending any command arms the session automatically. `/disarm` returns it to
terminal-friendly mode; `/arm` forces armed mode.

> While the hook is waiting, that session's terminal is busy ("thinking"). If a
> session goes idle before your message arrives, press Enter in its terminal to
> let the next `Stop` hook pick the command up.

### Topic commands

| command | effect |
|---|---|
| `/status` | label, armed/paused state, queued command count |
| `/arm` / `/disarm` | toggle the long wait window |
| `/pause` / `/resume` | hold / release queued commands |
| `/stop` | stop injecting into this session |
| `/sessions` | list all known sessions |
| `/help` | this list |

## Managing the broker

```bash
uv run bridge status      # broker + per-session state
uv run bridge logs -f     # tail ~/.claude/bridge/state/broker.log
uv run bridge restart
uv run bridge stop
uv run bridge uninstall-hooks
```

### Keep the broker always running (systemd --user)

```ini
# ~/.config/systemd/user/claude-tg-bridge.service
[Unit]
Description=claude-tg-bridge broker (Claude Code <-> Telegram)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%h/claude-tg-bridge/.venv/bin/bridge run
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now claude-tg-bridge.service
loginctl enable-linger "$USER"     # keep it running with no login / after reboot
```

Manage it:

```bash
systemctl --user status  claude-tg-bridge.service
systemctl --user restart claude-tg-bridge.service   # after a code change
journalctl --user -u claude-tg-bridge.service -f    # or: bridge logs -f
```

Once it's a service, control it with `systemctl --user`, not `bridge start/stop`
(they'd fight over the pidfile).

## Configuration

`bridge setup` writes `~/.claude/bridge/config.json`:

| key | default | meaning |
|---|---|---|
| `bot_token` | – | Telegram bot token |
| `chat_id` | – | supergroup id (negative, `-100…`) |
| `poll_minutes` | 5 | armed `Stop` hook wait |
| `grace_seconds` | 5 | un-armed `Stop` hook wait |
| `max_reinjections` | 50 | safety cap on consecutive injections per session |

Each key can be overridden by an env var: `CLAUDE_TG_BOT_TOKEN`,
`CLAUDE_TG_CHAT_ID`, `CLAUDE_TG_POLL_MINUTES`, `CLAUDE_TG_GRACE_SECONDS`,
`CLAUDE_TG_MAX_REINJECTIONS`. `CLAUDE_TG_BRIDGE_HOME` relocates the whole state
directory (used by the test suite).

## Layout

```
~/claude-tg-bridge/            # code
  src/claude_tg_bridge/        # broker, cli, telegram client, config
  hooks/                       # session_start.py, stop.py, session_end.py (stdlib only)

~/.claude/bridge/              # runtime state (shared by broker + hooks)
  config.json
  state/{offset, broker.pid, broker.log}
  register/<sid>.json          # session_start -> broker creates a topic
  sessions/<sid>.json          # label, thread_id, status, armed, paused
  threads/<tid>                # -> sid
  inbox/<sid>.jsonl            # queued commands
  outbox/<sid>/<ts>.txt        # queued responses
  end/<sid>.json               # session_end -> broker marks ended
```

## Limitations

- Commands are consumed only when a turn ends (`Stop`). No mid-turn interrupt.
- A truly idle session (hook already timed out) needs one Enter in its terminal
  to resume.
- The bridge injects commands as a *user would*: it can run anything the session
  can. Only add the bot to a group you control, and keep the token secret.

## Troubleshooting

**`is_forum: None` / `the chat is not a forum`**
Topics isn't actually enabled on the group. Group name → Edit → Topics → on →
save. Confirm the group now shows a topic list.

**`not enough rights to create a topic`**
The bot is an admin but without *Manage Topics*. Group → admins → the bot →
enable **Manage Topics** → save. Check with:
```bash
uv run python -c "import httpx;from claude_tg_bridge.config import Config as C;c=C.load();b=f'https://api.telegram.org/bot{c.bot_token}';me=httpx.get(f'{b}/getMe').json()['result']['id'];print(httpx.get(f'{b}/getChatMember',params={'chat_id':c.chat_id,'user_id':me}).json()['result'].get('can_manage_topics'))"
```

**Bot sees no messages (`0 update(s)` during setup)**
Privacy mode + not an admin yet, or the message predates the bot joining. Make
it an admin, then send a *new* message.

**A session's replies show up in the group's *General* topic**
That session started **before** `bridge install-hooks`, so its `SessionStart`
never registered a topic. Current builds keep the `Stop` hook silent for
unregistered sessions; just start a fresh `claude` session. Delete the stray
General messages by hand.

**Every turn pauses ~5s before finishing**
Expected: the un-armed `Stop` hook glances for a command for `grace_seconds`.
Lower it in `~/.claude/bridge/config.json` (e.g. `2`, or `0` to disable the
glance entirely) — the hook re-reads config each turn, no restart needed. Only
registered/bridged sessions are affected; sessions with no topic return
instantly.

**Broker won't start: `broker already running`**
Stale pidfile or a real one. `systemctl --user status claude-tg-bridge` (if using
the service) or `cat ~/.claude/bridge/state/broker.pid`. If nothing is running,
`rm ~/.claude/bridge/state/broker.pid`.

**After editing broker code**
`systemctl --user restart claude-tg-bridge.service` (or `bridge restart` if you
run it by hand). Hook scripts are re-read each invocation — no restart needed.

## This machine (`host`) — current setup

Everything already wired on this host, so it can be managed without re-deriving it:

| thing | where |
|---|---|
| Code | `~/claude-tg-bridge/` (venv at `.venv/`, Python 3.12.14 via pyenv) |
| Runtime state | `~/.claude/bridge/` |
| Config | `~/.claude/bridge/config.json` — bot `@example_bot`, group **"YourGroup"** (`chat_id -100XXXXXXXXXXX`) |
| Hooks | installed into `~/.claude/settings.json` (SessionStart / Stop / SessionEnd). Backups: `~/.claude/settings.json.bak-*` |
| Broker service | `~/.config/systemd/user/claude-tg-bridge.service`, **enabled + linger on** — runs at boot, no login needed |
| Shell | pyenv init block appended to `~/.zshrc` |

Day-to-day:

```bash
systemctl --user status claude-tg-bridge.service        # is it up?
journalctl --user -u claude-tg-bridge.service -f        # live log
systemctl --user restart claude-tg-bridge.service       # after pulling code changes
~/claude-tg-bridge/.venv/bin/bridge status              # broker + per-session view
```

To rotate the bot token: edit `~/.claude/bridge/config.json`, then restart the
service. To tear the whole thing down:

```bash
systemctl --user disable --now claude-tg-bridge.service
rm ~/.config/systemd/user/claude-tg-bridge.service
~/claude-tg-bridge/.venv/bin/bridge uninstall-hooks     # restores settings.json (with backup)
# optional: loginctl disable-linger "$USER"; rm -rf ~/.claude/bridge
```
