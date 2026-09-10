# claude-bridge-telegram

Claude Code 세션을 텔레그램에서 조종하는 브리지. 세션마다 텔레그램 그룹 안에
**포럼 토픽**이 하나씩 생기고 — 세션의 프롬프트·응답은 그 토픽으로 흘러나오고,
토픽에 당신이 쓴 메시지는 돌고 있는 세션에 **바로** 주입된다 (세션이 무언가
하는 중이든 idle이든).

```
Claude Code 세션 ──훅(비블로킹)──▶ outbox/<sid>/ ──▶ 브로커 ──▶ 텔레그램 토픽
텔레그램 토픽 ──▶ 브로커(getUpdates) ──▶ 세션의 [uds-messaging] 소켓 ──▶ 세션
```

- **훅** (`hooks/*.py`, 표준 라이브러리만): `SessionStart` / `UserPromptSubmit` /
  `Stop` / `SessionEnd` 네 이벤트에서 실행. **전부 비블로킹** — `~/.claude/bridge/`
  아래에 작은 파일 하나 쓰고 즉시 종료한다.
- **브로커** (`bridge` 데몬): 텔레그램과 통신하는 유일한 프로세스. `getUpdates`를
  독점하므로 동시에 여러 세션이 돌아도 offset 경합이 없다. 텔레그램 메시지를
  세션에 넣는 것도 브로커가 직접 한다 (훅 안 거침).

> **세션에 어떻게 메시지를 넣나?** — Claude Code 2.x는 세션마다 유닉스 소켓
> (`$CLAUDE_CODE_MESSAGING_SOCKET`, 즉 `$XDG_RUNTIME_DIR/cc-socks/<pid>.sock`)을
> 열어두고, `$CLAUDE_CODE_MESSAGING_TOKEN`으로 인증한 클라이언트의 `user` 메시지를
> 세션 프롬프트 큐로 라우팅한다. `SessionStart` 훅이 이 소켓 경로·토큰을 기록하고,
> 브로커가 거기 접속해 텔레그램 메시지를 넣는다. 예전엔 `Stop` 훅이 턴 끝마다
> 몇 분씩 블로킹하며 명령을 기다렸지만, 이제 그런 대기는 없다.

> **`Stop` 훅이 뭔가?** — Claude Code가 한 턴의 응답을 마친 직후 실행되는 훅이다.
> 이름이 "Stop"이지만 세션을 멈추는 게 아니라 "응답 종료 시점"을 뜻한다. 여기선
> 그 턴의 마지막 응답을 토픽으로 미러링하는 용도로만 쓴다.

## 요구 사항

- Python 3.12 (`.python-version`으로 고정)
- 프로젝트 가상환경용 [uv](https://docs.astral.sh/uv/)
- Claude Code **2.x** (`[uds-messaging]` 소켓이 있는 버전)
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

레포는 **아무 경로에나** 두면 된다 (`~/code/…`, `/opt/…`, 어디든). 아래 예시의
`$REPO`만 원하는 위치로 바꿔서 실행:

```bash
REPO=~/code/claude-bridge-telegram          # 원하는 위치로
git clone https://github.com/breadum/claude-bridge-telegram "$REPO"
cd "$REPO"
uv sync                       # 락파일로 .venv 생성

uv run bridge setup           # 토큰 붙여넣기 → ~/.claude/bridge/config.json 생성 (chmod 600)
uv run bridge install-hooks   # ~/.claude/settings.json에 훅 추가 (절대경로로, 자동 백업)
./deploy/install-service.sh   # 브로커를 systemd --user 서비스로 상시 실행
```

`install-hooks`와 `install-service.sh`는 **스크립트 자기 위치에서 절대경로를
계산**하므로 레포가 어디에 있든 동작한다. 런타임 상태(`~/.claude/bridge/`)와
설정 파일은 코드 위치와 무관하게 항상 같은 곳이다.

- **레포를 옮기거나 이름을 바꾼 뒤**: 새 위치에서 `uv sync` →
  `uv run bridge install-hooks`(옛 절대경로 항목은 자동으로 안 지워지니, 먼저
  옛 위치에서 `uninstall-hooks` 하거나 `~/.claude/settings.json`을 직접 정리) →
  `./deploy/install-service.sh`(유닛을 새 경로로 다시 렌더).

임시로 돌려볼 땐 서비스 대신 `uv run bridge start` / `stop`.
`bridge`를 PATH에 올리려면: `uv tool install --editable "$REPO"`.

### 설정(토큰)은 어디에 있나

- **저장소에는 없다.** `bridge setup`이 `~/.claude/bridge/config.json`에 쓴다 —
  머신마다 로컬, git에 안 올라간다.
- 브로커(`bridge run`)가 실행될 때마다 `$HOME/.claude/bridge/config.json`을
  읽는다. systemd 유닛은 토큰도 레포 경로 규칙도 참조하지 않는다 — 다만 `HOME`이
  설정돼 있어야 하고(`systemd --user`가 넣어준다), 유닛의 `ExecStart`에는
  `install-service.sh`가 넣어준 `.venv/bin/bridge`의 절대경로가 박힌다.
- 훅은 config를 아예 안 읽는다 (토픽·텔레그램·주입 전부 브로커 몫).
- 다른 머신 = 위 세 줄을 그 머신에서 다시 실행. 코드는 `git pull`, 토큰은 그 머신
  `config.json`에.

## 3. 사용

아무 디렉터리에서 Claude Code 세션을 시작한다. `myrepo-3f2a`
(`<디렉터리명>-<세션ID 앞 4자리>`) 형태의 토픽이 헤더 메시지와 함께 그룹에
나타난다.

- 세션의 프롬프트(`🧑`)와 응답(`🤖`)이 그 토픽에 미러링된다.
- **토픽에 메시지를 쓰면 곧바로(≈수 초 내) 세션에 주입된다** — 세션이 턴 중이든
  idle이든 상관없다. 대기·arm 같은 건 없다.
- 브로커가 꺼져 있으면 주입이 안 된다. 소켓이 잠깐 안 잡히면(세션 재시작 등)
  메시지는 `inbox/`에 큐잉됐다가 매 루프 재시도된다.

### 권한 (중요)

브로커가 넣는 메시지는 세션에 **peer(다른 Claude 세션) 메시지**로 도착한다 —
1인칭 유저 입력이 아니다. 그래서:

- **네이티브 도구 권한 프롬프트를 없애지 못한다.** 텔레그램에서 "yes"를 보내도
  그 다이얼로그는 안 닫힌다.
- 텔레그램으로 구동할 세션은 `claude --dangerously-skip-permissions`(또는 신뢰
  폴더 + `acceptEdits` 등)로 시작해야 매끄럽다. 이건 브리지가 못 없애는 셋업
  요구사항이다.
- 작업 지시 자체는 정상 처리된다. peer 신뢰도로 취급되는 것뿐이라, 권한·설정
  변경 같은 민감한 요청은 세션이 거절할 수 있다.

### 토픽 명령

| 명령 | 효과 |
|---|---|
| `/status` | 라벨, 상태, 소켓 도달 가능 여부, 재시도 대기 수, cwd |
| `/stop` | 이 세션에 더 이상 메시지를 전달하지 않음 (토픽은 남김) |
| `/close` | `/stop` 한 뒤 **이 토픽을 삭제**하고 로컬 상태 정리 |
| `/title <text>` | 이 토픽 이름 변경 |
| `/sessions` | 알려진 모든 세션 목록 |
| `/help` | 이 목록 |

토픽 이름은 **Claude Code가 세션에 붙인 제목**을 그대로 가져온다. Claude Code는
첫 교환 뒤 대화 제목을 스스로 지어 트랜스크립트에 기록하는데(`ai-title`),
`Stop` 훅이 그걸 실어 보내면 브로커가 토픽 이름으로 쓴다. 제목이 나오기 전까지는
`<디렉터리> …`. 한 번 지정한 뒤엔 자동으로 바꾸지 않는다 — `/title <text>`로
언제든 덮어쓴다. (별도 API 키 불필요.)

### 세션 종료 / 토픽 정리

- **한 세션만**: 그 토픽에서 `/close` — 토픽이 삭제되고 로컬 상태(`sessions/`,
  `threads/`, `inbox/` 등)도 지워진다.
- **끝난 세션 일괄**: `uv run bridge prune` — `status`가 `ended`인 세션의 토픽 +
  상태를 모두 삭제. 브로커가 켜져 있어도 안전하다.
- **전부**: `uv run bridge prune --all` (확인 프롬프트, `-y`로 건너뛰기).
- **세션에서 `/exit`** 하면 `SessionEnd` 훅이 돈다. 기본 동작: 상태를 `ended`로
  표시 + 토픽에 "🔴 session ended." → **토픽은 남는다** (스크롤백 보존).
- `/exit` 시 토픽도 바로 지우려면 `~/.claude/bridge/config.json`에
  `"delete_topic_on_end": true` → 브로커 재시작.

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

```
deploy/
  claude-bridge-telegram.service.in  # 유닛 템플릿 (@REPO_DIR@ / @BRIDGE_BIN@ 자리표시자)
  install-service.sh                 # 템플릿을 실제 경로로 렌더 → ~/.config/systemd/user/ 에 설치
                                     #   → daemon-reload → enable --now → enable-linger
  uninstall-service.sh               # disable --now → 유닛 삭제 (훅/상태는 안 건드림)
```

`install-service.sh`가 스크립트 위치에서 레포 경로를 알아내 템플릿의
`@REPO_DIR@`(→ `WorkingDirectory`), `@BRIDGE_BIN@`(→ `ExecStart`)을 채운다.
레포가 어디에 있든 되고, **레포를 옮기면 이 스크립트만 다시 실행**하면 된다.

```bash
uv sync                           # .venv 먼저
./deploy/install-service.sh       # 멱등 — 템플릿 수정/레포 이동 후 다시 실행
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
| `delete_topic_on_end` | `false` | 세션 종료 시 토픽도 삭제할지. `false`면 토픽은 남고 나중에 `/close`·`bridge prune`으로 정리 |

환경 변수 오버라이드: `CLAUDE_TG_BOT_TOKEN`, `CLAUDE_TG_CHAT_ID`,
`CLAUDE_TG_DELETE_TOPIC_ON_END`.
`CLAUDE_TG_BRIDGE_HOME`는 상태 디렉터리 전체를 옮긴다 (테스트에서 사용).

> **그룹 이름을 바꿔도 설정은 그대로다.** 브리지는 `chat_id`(숫자)만 쓰고 그룹
> 제목은 읽지 않는다. 세션별 토픽 이름을 텔레그램에서 바꿔도 무관하다 (라우팅은
> `message_thread_id` 기준). config를 바꿔야 하는 경우는 그룹을 삭제하고 새로
> 만들 때뿐이다.

## 디렉터리 구조

```
<레포>/                              # 코드 — 아무 경로
  src/claude_bridge_telegram/        # broker, cli, telegram client, inject, config
  hooks/                             # session_start / user_prompt_submit / stop / session_end (stdlib 전용)
  deploy/                            # systemd 유닛 템플릿 + 설치 스크립트
  tests/                             # pytest (네트워크·실제 ~/.claude 안 씀)

~/.claude/bridge/                    # 런타임 상태 (브로커 + 훅 공유)
  config.json
  state/{offset, broker.pid, broker.log}
  register/<sid>.json                # session_start → 브로커가 토픽 생성/갱신 (+ messaging_socket/token/pid)
  sessions/<sid>.json                # label, thread_id, status, titled, messaging_socket, messaging_token
  threads/<tid>                      # → sid
  inbox/<sid>.jsonl                  # 주입 실패해 재시도 대기 중인 메시지
  outbox/<sid>/<ts>.json             # {"role","text"} 대기 중인 아웃바운드
  end/<sid>.json                     # session_end → 브로커가 종료 처리
```

## 한계

- **브로커가 켜져 있어야** 텔레그램 → 세션 주입이 된다 (미러링도). 서비스로
  상시 실행 권장.
- 주입 메시지는 peer 프레이밍이라 네이티브 권한 프롬프트를 못 없앤다 →
  `--dangerously-skip-permissions` 로 세션 시작 ([권한](#권한-중요) 참고).
- 턴 도중 인터럽트는 불가 — 주입한 메시지는 현재 턴 뒤에 처리된다.
- Claude Code 1.x 등 `[uds-messaging]` 소켓이 없는 세션은 **미러 전용**이다
  (토픽 헤더에 그렇게 표시됨). `/close`로 정리.

## 문제 해결

**`is_forum: None` / `the chat is not a forum`**
그룹에 Topics가 실제로 안 켜져 있다. 그룹 이름 → 편집 → Topics → 켜기 → 저장.

**`not enough rights to create a topic`**
봇이 관리자지만 *주제 관리(Manage Topics)* 권한이 없다. 그룹 → 관리자 → 봇 →
**주제 관리** 켜기 → 저장.

**봇이 메시지를 못 받음 (`setup` 중 `0 update(s)`)**
privacy mode + 아직 관리자 아님, 또는 봇 합류 이전 메시지다. 관리자로 만든 뒤
*새* 메시지를 보낸다.

**토픽에 메시지를 보내도 세션에 안 들어감**
- 브로커가 떠 있나: `bridge status` / `systemctl --user status claude-bridge-telegram.service`
- `/status` 로 `socket: ok` 인지 확인. `missing`이면 세션이 재시작돼 pid가 바뀐
  것 — 세션에서 아무 프롬프트나 한 번 주면 `SessionStart` 훅이 소켓을 갱신한다.
- `unknown`이면 그 세션이 `[uds-messaging]` 없이 떠서 미러 전용이다.

**세션 응답이 그룹의 *General* 토픽에 표시됨**
그 세션이 `bridge install-hooks` **이전에** 시작돼서 등록되지 않았다. 현재
빌드는 등록 안 된 세션엔 `Stop` 훅이 침묵한다 — 새 `claude` 세션을 시작하면 된다.

**브로커가 안 뜸: `broker already running`**
stale pidfile이거나 진짜 실행 중이다. `cat ~/.claude/bridge/state/broker.pid`,
아무것도 안 돌면 `rm` 후 재시작.

**브로커 코드를 수정한 뒤**
`systemctl --user restart claude-bridge-telegram.service` (직접 실행 중이면
`bridge restart`). 훅 스크립트는 매 호출마다 다시 읽으므로 재시작 불필요.

## 기여 / 개발

`CLAUDE.md`에 아키텍처 불변식과 개발 규칙이 정리돼 있다. 요약:

```bash
uv sync
uv run ruff check .
uv run pytest
```

- 훅은 **stdlib 전용·비블로킹**. 텔레그램은 브로커만 호출.
- `outbox` JSON 스키마를 바꾸면 훅 쪽(`_bridge_common.queue_outbox`)과
  브로커 쪽(`_read_outbox_item`)을 같이 고칠 것.
- 봇 토큰은 `~/.claude/bridge/config.json`에만. 커밋 전 토큰 스캔.

## 이 머신 (`host`) — 현재 설정

| 항목 | 위치 |
|---|---|
| 코드 | `~/claude-bridge-telegram/` (`.venv/`, pyenv Python 3.12.14) |
| 런타임 상태 | `~/.claude/bridge/` |
| 설정 | `~/.claude/bridge/config.json` — 봇 `@example_bot`, 그룹 **"YourGroup"** (`chat_id -100XXXXXXXXXXX`), `delete_topic_on_end: true`. (예전 `poll_minutes`/`arm_on_start` 키는 이제 무시됨 — 지워도 됨) |
| 훅 | `uds-messaging` 리팩터 중 `bridge uninstall-hooks`로 제거됨. 새 버전 쓰려면 `uv run bridge install-hooks` 다시 |
| 브로커 서비스 | `~/.config/systemd/user/claude-bridge-telegram.service`, **enabled + linger** — 부팅 시 실행 |
| 셸 | `~/.zshrc`에 pyenv init 블록 |

```bash
systemctl --user restart claude-bridge-telegram.service       # 코드 변경 반영
journalctl --user -u claude-bridge-telegram.service -f        # 실시간 로그
~/claude-bridge-telegram/.venv/bin/bridge status              # 브로커 + 세션별 뷰
```

전체 제거:

```bash
systemctl --user disable --now claude-bridge-telegram.service
rm ~/.config/systemd/user/claude-bridge-telegram.service
~/claude-bridge-telegram/.venv/bin/bridge uninstall-hooks
# 선택: loginctl disable-linger "$USER"; rm -rf ~/.claude/bridge
```
