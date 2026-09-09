# claude-bridge-telegram

Claude Code 세션을 텔레그램에서 조종하는 브리지. 세션마다 텔레그램 그룹 안에
**포럼 토픽**이 하나씩 생기고 — 세션의 응답은 그 토픽으로 흘러나오고, 토픽에
당신이 입력한 메시지는 세션의 다음 지시로 주입된다.

```
Claude Code 세션 ──Stop 훅──▶ outbox/<sid>/ ──▶ 브로커 ──▶ 텔레그램 토픽
텔레그램 토픽 ──▶ 브로커(getUpdates) ──▶ inbox/<sid> ──Stop 훅──▶ 세션
```

- **훅** (`hooks/*.py`, 표준 라이브러리만 사용): `SessionStart` / `Stop` /
  `SessionEnd` 세 이벤트에서 실행된다. `~/.claude/bridge/` 아래 파일만 건드린다.
- **브로커** (`bridge` 데몬): 텔레그램과 통신하는 유일한 프로세스. `getUpdates`를
  독점하므로 동시에 여러 세션이 돌아도 offset 경합이 없다.

> **`Stop` 훅이 뭔가?** — Claude Code가 한 턴의 응답을 **마친 직후** 실행되는 훅
> 이다. 이름이 "Stop"이지만 세션을 멈추는 게 아니라 "응답 종료 시점"을 뜻한다.
> 이 브리지의 핵심 동작(응답 내보내기 + 명령 주입)이 전부 여기서 일어난다.
> Claude Code에 "PostHook" 같은 건 없고, 이 `Stop`이 그 역할이다.

## 요구 사항

- Python 3.12 (`.python-version`으로 고정, pyenv로 빌드)
- 프로젝트 가상환경용 [uv](https://docs.astral.sh/uv/)
- 텔레그램 봇 + **Topics(주제)가 켜진 슈퍼그룹**

## 1. 텔레그램 봇 & 그룹 만들기

1. [@BotFather](https://t.me/BotFather) → `/newbot` → **토큰** 복사.
2. 그룹을 만든다. **그룹 이름 → 편집 → Topics**를 켜고 저장한다. 저장 후 그룹에
   토픽 목록 / "General" 토픽이 실제로 보여야 한다 — `getChat`이 `is_forum: true`
   를 반환해야 한다.
3. **봇을 그룹에 추가한 뒤 관리자로 승격**한다. 관리자 권한 화면에서 **주제 관리
   (Manage Topics)**를 반드시 직접 켜야 한다 (관리자라도 기본은 꺼져 있는 경우가
   많다). 관리자가 되면 봇이 모든 메시지를 볼 수 있다 (privacy mode 우회).
4. 봇이 관리자가 **된 뒤에** 그룹에 메시지를 하나 보낸다 — 봇이 합류/승격되기
   전의 메시지는 봇에게 전달되지 않는다.

이 중 뭔가 잘못되면 `bridge setup` 또는 브로커 로그에서 바로 드러난다:
`is_forum: None`, `the chat is not a forum`, `not enough rights to create a
topic`. → [문제 해결](#문제-해결) 참고.

## 2. 설치

```bash
git clone https://github.com/breadum/claude-bridge-telegram ~/claude-bridge-telegram
cd ~/claude-bridge-telegram
uv sync                       # 락파일로 .venv 생성

uv run bridge setup           # 토큰 붙여넣기 → ~/.claude/bridge/config.json 생성 (chmod 600)
uv run bridge install-hooks   # ~/.claude/settings.json에 훅 추가 (자동 백업)
./deploy/install-service.sh   # 브로커를 systemd --user 서비스로 상시 실행
```

임시로 돌려볼 땐 서비스 대신 `uv run bridge start` / `stop`.
`bridge`를 PATH에 올리려면: `uv tool install --editable ~/claude-bridge-telegram`.

### 설정(토큰)은 어디에 있나

- **저장소에는 없다.** `bridge setup`이 `~/.claude/bridge/config.json`에 쓴다 —
  머신마다 로컬, git에 안 올라간다.
- 브로커(`bridge run`)가 실행될 때마다 `$HOME/.claude/bridge/config.json`을
  읽는다. systemd 유닛은 토큰을 참조하지 않는다 (그래서 `HOME`이 설정돼 있어야
  한다 — `systemd --user`가 넣어준다).
- 훅은 이 파일에서 타이밍 값만 읽고 토큰은 안 쓴다 (텔레그램은 브로커만 호출).
- 다른 머신 = 위 3줄을 그 머신에서 다시 실행. 코드는 `git pull`, 토큰은 그 머신
  `config.json`에.

## 3. 사용

아무 디렉터리에서 Claude Code 세션을 시작한다. `myrepo-3f2a`
(`<디렉터리명>-<세션ID 앞 4자리>`) 형태의 토픽이 헤더 메시지와 함께 그룹에
나타난다.

- 세션의 모든 응답이 그 토픽에 표시된다.
- 토픽에 메시지를 입력하면 → 세션의 다음 지시가 된다.
- **첫 메시지**를 보내면 세션이 *arm* 된다 (아래 참고).

### armed / un-armed

매 턴이 끝나면 `Stop` 훅은 세션을 idle로 보내기 전에 명령을 기다린다:

| 상태 | 대기 시간 | 이유 |
|---|---|---|
| **un-armed** (기본) | `grace_seconds` (5초) | 일반 터미널 사용을 오래 막지 않도록 |
| **armed** | `poll_minutes` (5분) | 텔레그램만으로 세션을 끝까지 조종할 수 있도록 |

명령을 한 번 보내면 자동으로 arm 된다. `/disarm`으로 터미널 친화 모드로 되돌리고,
`/arm`으로 강제 arm 한다.

> 훅이 대기하는 동안 해당 세션 터미널은 "생각 중" 상태로 묶인다. 메시지가 도착하기
> 전에 세션이 idle로 빠졌다면, 그 터미널에서 엔터를 한 번 눌러 다음 `Stop` 훅이
> 명령을 집어가게 하면 된다.

### 토픽 명령

| 명령 | 효과 |
|---|---|
| `/status` | 라벨, armed/paused 상태, 대기 중인 명령 수 |
| `/arm` / `/disarm` | 긴 대기 창 켜기 / 끄기 |
| `/pause` / `/resume` | 명령 보류 / 재개 |
| `/stop` | 이 세션에 대한 명령 주입 중단 (토픽은 남김) |
| `/close` | `/stop` 한 뒤 **이 토픽을 삭제**하고 세션 상태 정리 |
| `/sessions` | 알려진 모든 세션 목록 |
| `/help` | 이 목록 |

### 세션 종료 / 토픽 정리

- **한 세션만**: 그 토픽에서 `/close` — 토픽이 삭제되고 로컬 상태(`sessions/`,
  `threads/`, `inbox/` 등)도 지워진다. (텔레그램에서 토픽을 길게 눌러 직접
  삭제해도 됨 — 다음 `bridge prune`이 남은 상태를 청소한다.)
- **끝난 세션 일괄**: `uv run bridge prune` — `status`가 `ended`인 세션의 토픽 +
  상태를 모두 삭제. 브로커가 켜져 있어도 안전하다.
- **전부**: `uv run bridge prune --all` (확인 프롬프트, `-y`로 건너뛰기).
- **세션에서 그냥 `/exit`** 하면 `SessionEnd` 훅이 돈다. 기본 동작은:
  상태를 `ended`로 표시 + 토픽에 "🔴 session ended." → **토픽은 남는다**
  (`/close`·`bridge prune` 전까지). 스크롤백을 보존하려는 의도.
- `/exit` 할 때 토픽도 바로 지우고 싶으면 `~/.claude/bridge/config.json`에
  `"delete_topic_on_end": true` → 브로커 재시작. 그러면 세션 종료 즉시 토픽 삭제.

## 브로커 관리

```bash
uv run bridge status         # 브로커 + 세션별 상태
uv run bridge logs -f        # ~/.claude/bridge/state/broker.log tail
uv run bridge restart
uv run bridge stop
uv run bridge prune          # 끝난 세션 토픽 + 상태 삭제 (--all / -y)
uv run bridge uninstall-hooks
```

### 브로커를 항상 켜두기 (systemd --user)

유닛 파일과 설치 스크립트는 저장소의 [`deploy/`](deploy/)에 있다:

```
deploy/
  claude-bridge-telegram.service   # systemd --user 유닛 (%h = 홈, 레포는 ~/claude-bridge-telegram 가정)
  install-service.sh               # 유닛 복사 → daemon-reload → enable --now → enable-linger
  uninstall-service.sh             # disable --now → 유닛 삭제 (훅/상태는 안 건드림)
```

```bash
uv sync                           # .venv 먼저
./deploy/install-service.sh       # 멱등 — 유닛 수정/레포 이동 후 다시 실행
```

관리:

```bash
systemctl --user status  claude-bridge-telegram.service
systemctl --user restart claude-bridge-telegram.service   # 코드 수정 후
journalctl --user -u claude-bridge-telegram.service -f    # 또는: bridge logs -f
```

서비스로 돌리는 동안엔 `bridge start/stop` 대신 `systemctl --user`로 제어한다
(pidfile을 두고 서로 충돌한다).

## 설정

`bridge setup`이 `~/.claude/bridge/config.json`을 쓴다:

| 키 | 기본값 | 의미 |
|---|---|---|
| `bot_token` | – | 텔레그램 봇 토큰 |
| `chat_id` | – | 슈퍼그룹 ID (음수, `-100…`) |
| `poll_minutes` | 5 | armed 상태 `Stop` 훅 대기 (분) |
| `grace_seconds` | 5 | un-armed 상태 `Stop` 훅 대기 (초) |
| `max_reinjections` | 50 | 세션당 연속 주입 안전 상한 |
| `delete_topic_on_end` | `false` | 세션 종료 시 토픽도 삭제할지. `false`면 토픽은 남고 나중에 `/close`·`bridge prune`으로 정리 |

각 키는 환경 변수로 덮어쓸 수 있다: `CLAUDE_TG_BOT_TOKEN`,
`CLAUDE_TG_CHAT_ID`, `CLAUDE_TG_POLL_MINUTES`, `CLAUDE_TG_GRACE_SECONDS`,
`CLAUDE_TG_MAX_REINJECTIONS`, `CLAUDE_TG_DELETE_TOPIC_ON_END`.
`CLAUDE_TG_BRIDGE_HOME`는 상태 디렉터리 전체를 옮긴다 (테스트에서 사용).

> **그룹 이름을 바꿔도 설정은 그대로다.** 브리지는 `chat_id`(숫자)만 쓰고 그룹
> 제목은 읽지 않는다. 세션별 토픽 이름을 텔레그램에서 바꿔도 무관하다 (라우팅은
> `message_thread_id` 기준). config를 바꿔야 하는 경우는 그룹을 삭제하고 새로
> 만들 때뿐이다.

## 디렉터리 구조

```
~/claude-bridge-telegram/            # 코드
  src/claude_bridge_telegram/        # broker, cli, telegram client, config
  hooks/                       # session_start.py, stop.py, session_end.py (stdlib 전용)

~/.claude/bridge/              # 런타임 상태 (브로커 + 훅 공유)
  config.json
  state/{offset, broker.pid, broker.log}
  register/<sid>.json          # session_start → 브로커가 토픽 생성
  sessions/<sid>.json          # label, thread_id, status, armed, paused
  threads/<tid>                # → sid
  inbox/<sid>.jsonl            # 대기 중인 명령
  outbox/<sid>/<ts>.txt        # 대기 중인 응답
  end/<sid>.json               # session_end → 브로커가 종료 표시
```

## 한계

- 명령은 턴이 끝날 때(`Stop`)만 소비된다. 턴 도중 인터럽트는 불가.
- 완전히 idle이 된 세션(훅이 이미 타임아웃)은 그 터미널에서 엔터를 한 번 눌러야
  재개된다.
- 브리지는 *사용자가 하듯이* 명령을 주입한다 — 세션이 할 수 있는 건 다 할 수
  있다. 본인이 통제하는 그룹에만 봇을 넣고, 토큰은 비밀로 유지할 것.

## 문제 해결

**`is_forum: None` / `the chat is not a forum`**
그룹에 Topics가 실제로 안 켜져 있다. 그룹 이름 → 편집 → Topics → 켜기 → 저장.
그룹에 토픽 목록이 보이는지 확인.

**`not enough rights to create a topic`**
봇이 관리자지만 *주제 관리(Manage Topics)* 권한이 없다. 그룹 → 관리자 → 봇 →
**주제 관리** 켜기 → 저장. 확인:
```bash
uv run python -c "import httpx;from claude_bridge_telegram.config import Config as C;c=C.load();b=f'https://api.telegram.org/bot{c.bot_token}';me=httpx.get(f'{b}/getMe').json()['result']['id'];print(httpx.get(f'{b}/getChatMember',params={'chat_id':c.chat_id,'user_id':me}).json()['result'].get('can_manage_topics'))"
```

**봇이 메시지를 못 받음 (`setup` 중 `0 update(s)`)**
privacy mode + 아직 관리자 아님, 또는 봇 합류 이전 메시지다. 관리자로 만든 뒤
*새* 메시지를 보낸다.

**세션 응답이 그룹의 *General* 토픽에 표시됨**
그 세션이 `bridge install-hooks` **이전에** 시작돼서 `SessionStart`가 토픽을
등록하지 못했다. 현재 빌드는 등록되지 않은 세션에 대해 `Stop` 훅이 침묵한다 —
새 `claude` 세션을 시작하면 된다. General에 남은 메시지는 직접 삭제.

**매 턴이 끝날 때 ~5초 멈춤**
정상이다. un-armed `Stop` 훅이 `grace_seconds` 동안 명령을 살핀다.
`~/.claude/bridge/config.json`에서 낮추면 된다 (예: `2`, 또는 `0`으로 완전히
끄기) — 훅이 매 턴 config를 다시 읽으므로 재시작 불필요. 등록된(브리지된) 세션만
영향을 받고, 토픽이 없는 세션은 즉시 반환한다.

**브로커가 안 뜸: `broker already running`**
stale pidfile이거나 진짜로 실행 중이다. 서비스를 쓰면
`systemctl --user status claude-bridge-telegram`, 아니면
`cat ~/.claude/bridge/state/broker.pid`. 아무것도 안 돌고 있으면
`rm ~/.claude/bridge/state/broker.pid`.

**브로커 코드를 수정한 뒤**
`systemctl --user restart claude-bridge-telegram.service` (직접 실행 중이면
`bridge restart`). 훅 스크립트는 매 호출마다 다시 읽으므로 재시작 불필요.

## 이 머신 (`host`) — 현재 설정

이 호스트에 이미 구성된 것들. 다시 파악할 필요 없이 관리할 수 있도록 정리:

| 항목 | 위치 |
|---|---|
| 코드 | `~/claude-bridge-telegram/` (`.venv/`, pyenv로 빌드한 Python 3.12.14) |
| 런타임 상태 | `~/.claude/bridge/` |
| 설정 | `~/.claude/bridge/config.json` — 봇 `@example_bot`, 그룹 **"YourGroup"** (`chat_id -100XXXXXXXXXXX`) |
| 훅 | `~/.claude/settings.json`에 설치됨 (SessionStart / Stop / SessionEnd). 백업: `~/.claude/settings.json.bak-*` |
| 브로커 서비스 | `~/.config/systemd/user/claude-bridge-telegram.service`, **enabled + linger 켜짐** — 부팅 시 실행, 로그인 불필요 |
| 셸 | `~/.zshrc`에 pyenv init 블록 추가됨 |

일상 관리:

```bash
systemctl --user status claude-bridge-telegram.service        # 살아있나?
journalctl --user -u claude-bridge-telegram.service -f        # 실시간 로그
systemctl --user restart claude-bridge-telegram.service       # 코드 변경 반영
~/claude-bridge-telegram/.venv/bin/bridge status              # 브로커 + 세션별 뷰
```

봇 토큰 교체: `~/.claude/bridge/config.json` 수정 후 서비스 재시작. 전체 제거:

```bash
systemctl --user disable --now claude-bridge-telegram.service
rm ~/.config/systemd/user/claude-bridge-telegram.service
~/claude-bridge-telegram/.venv/bin/bridge uninstall-hooks     # settings.json 복원 (백업됨)
# 선택: loginctl disable-linger "$USER"; rm -rf ~/.claude/bridge
```
