# claude-bridge-telegram

Claude Code 세션을 텔레그램에서 조종하는 브리지. 세션마다 텔레그램 그룹에
**포럼 토픽**이 하나씩 생긴다 — 세션의 프롬프트·응답은 그 토픽으로 흘러나오고,
토픽에 쓴 메시지는 돌고 있는 세션에 **바로** 주입된다 (턴 중이든 idle이든).

```
세션 ──훅(비블로킹)──▶ ~/.claude/bridge/outbox ──▶ 브로커 ──▶ 텔레그램 토픽
텔레그램 토픽 ──▶ 브로커 ──▶ 세션의 [uds-messaging] 소켓 ──▶ 세션
```

## 구성 요소

| | 역할 |
|---|---|
| **훅** `hooks/*.py` | `SessionStart`·`UserPromptSubmit`·`Stop`·`SessionEnd`·`Notification` 다섯 이벤트에서 실행. 표준 라이브러리만 쓰고 **전부 비블로킹** — `~/.claude/bridge/`에 작은 파일 하나 쓰고 끝. |
| **브로커** `bridge` 데몬 | 텔레그램과 통신하는 **유일한** 프로세스. 토픽 생성, 응답 미러링, 그리고 텔레그램 메시지를 세션 소켓에 직접 주입. `getUpdates`를 독점하므로 세션이 여러 개 돌아도 경합이 없다. |

주입 경로: Claude Code 2.x는 세션마다 유닉스 소켓(`$CLAUDE_CODE_MESSAGING_SOCKET`)을
열어두고, `$CLAUDE_CODE_MESSAGING_TOKEN`으로 인증한 클라이언트의 메시지를 세션
프롬프트 큐로 넣어준다. `SessionStart` 훅이 이 소켓·토큰을 기록하면 브로커가 거기
접속한다.

> `Stop` 훅은 세션 종료가 아니라 "한 턴의 응답이 끝난 시점"에 실행되는 훅이다.
> 여기선 그 응답을 토픽으로 내보내는 데만 쓴다.

## 동작 조건

브리지가 세션을 잡으려면 아래가 **모두** 참이어야 한다:

- **Claude Code 2.x** — `[uds-messaging]` 소켓이 있는 버전. 1.x 세션은 응답
  미러링만 되고 주입은 안 된다 (토픽 헤더에 "미러 전용"으로 표시).
- **브로커가 실행 중** — 꺼져 있으면 미러링도 주입도 멈춘다. systemd 서비스 권장.
- **세션이 `bridge install-hooks` *이후에* 시작됨** — 그 전에 뜬 세션은 등록되지
  않아 훅이 침묵한다.
- **텔레그램** — Topics가 켜진 슈퍼그룹 + 봇이 그 그룹의 관리자이고 *주제
  관리(Manage Topics)* 권한 보유.
- **`~/.claude/settings.json`에 `"crossSessionInbound": "accept"`** — 없으면
  Claude Code가 브로커발 peer 메시지를 세션에 전달하지 않고 **보류(held)**한다
  ([권한](#권한) 참고).
- **주입할 세션은 `claude --dangerously-skip-permissions`로 시작** — 주입
  메시지는 peer 프레이밍이라 네이티브 권한 프롬프트를 못 없앤다.

## 설치

[uv](https://docs.astral.sh/uv/)가 필요하다 (Python 3.12는 uv가
`.python-version`을 보고 받아온다).

### 1. 텔레그램 봇 + 그룹

1. [@BotFather](https://t.me/BotFather) → `/newbot` → **토큰** 복사.
2. 슈퍼그룹 생성 → **그룹 편집 → Topics 켜기**. (`getChat`이 `is_forum: true`여야 한다.)
3. 봇을 그룹에 추가 → **관리자로 승격** → 관리자 권한 화면에서 **주제 관리(Manage
   Topics)**를 직접 켠다 (관리자라도 기본은 꺼져 있다).
4. 봇이 관리자가 된 *뒤에* 그룹에 메시지를 하나 보낸다 — 그 전 메시지는 봇에게
   전달되지 않는다.

문제가 있으면 `bridge setup`이나 브로커 로그에 그대로 찍힌다 → [문제 해결](#문제-해결).

### 2. 브리지

레포는 아무 경로에나 둬도 된다. 런타임 상태(`~/.claude/bridge/`)와 설정 파일은
코드 위치와 무관하게 늘 같은 곳이다.

```bash
git clone https://github.com/breadum/claude-bridge-telegram
cd claude-bridge-telegram
uv sync                       # 락파일로 .venv 생성

uv run bridge setup           # 봇 토큰 입력 → ~/.claude/bridge/config.json (chmod 600)
uv run bridge install-hooks   # ~/.claude/settings.json에 훅 5개 추가 (절대경로, 자동 백업)
./service/install.sh          # 브로커를 systemd --user 서비스로 상시 실행
```

그리고 `~/.claude/settings.json`에 아래를 직접 추가한다 (없으면 텔레그램 메시지가
세션에 안 들어가고 보류된다 — [권한](#권한) 참고):

```json
"crossSessionInbound": "accept"
```

`install-hooks`와 `service/install.sh`는 스크립트 자기 위치에서 절대경로를
계산하므로 레포가 어디 있든 동작한다.

- 임시로만 돌려볼 땐 서비스 대신 `uv run bridge start` / `bridge stop`.
- `bridge`를 PATH에 올리려면 `uv tool install --editable .`.
- **레포를 옮겼다면**: 옛 위치에서 `bridge uninstall-hooks` → 새 위치에서
  `uv sync` → `bridge install-hooks` → `./service/install.sh`.

### 3. 첫 세션

아무 디렉터리에서 `claude --dangerously-skip-permissions` 를 실행한다.
`<디렉터리>-<세션ID 4자리>` 형태의 토픽이 헤더 메시지와 함께 그룹에 나타난다.

## 사용

- 프롬프트(`🧑`)와 응답(`🤖`)이 토픽에 미러링된다. Claude의 Markdown은 텔레그램
  HTML(굵게·기울임·`코드`·코드블록·인용·링크)로 변환돼 나간다. 표는 고정폭
  블록으로, 표현 못 하는 서식은 평문으로 떨어진다.
- 백그라운드 작업 완료·로컬 슬래시 명령 같은 기계 발생 턴은 한 줄 이벤트(`🔔`)로
  정리되고, 순수 노이즈(빈 출력·컨텍스트 주입 블록)는 미러링하지 않는다.
- 세션이 **입력·권한을 기다리면** (`Notification` 훅) `🔔`로 알려준다 — 예:
  `🔔 Claude needs your permission to use Bash`. 권장 설정(`--dangerously-skip-permissions`)
  이면 권한 프롬프트 자체가 없으니, 이 알림은 주로 Claude가 `AskUserQuestion`을
  쓸 때 뜬다. 답은 토픽에 그냥 쓰면 프롬프트 큐에 들어간다 (선택창이 타임아웃된
  뒤 처리). 단순 "your turn" idle 알림은 걸러진다.
- **토픽에 메시지를 쓰면 몇 초 내로 세션에 주입된다** — 턴 중이든 idle이든. 대기·
  arm 같은 건 없다.
- 소켓이 잠깐 안 잡히면(세션 재시작 등) 메시지는 `inbox/`에 큐잉됐다가 매 루프
  자동 재시도된다.

### 토픽 명령

| 명령 | 효과 |
|---|---|
| `/status` | 라벨, 상태, 소켓 도달 여부, 재시도 대기 수, cwd |
| `/stop` | 이 세션에 더 이상 전달 안 함 (토픽은 유지) |
| `/close` | `/stop` + 토픽 삭제 + 로컬 상태 정리 |
| `/title <text>` | 토픽 이름 수동 변경 |
| `/sessions` | 전체 세션 목록 |
| `/help` | 명령 목록 |

### 권한

브로커가 넣는 메시지는 세션에 **peer 메시지**(다른 Claude 세션발)로 도착한다 —
1인칭 유저 입력이 아니다. 그래서 두 가지를 설정해야 무인 구동이 매끄럽다:

1. **`~/.claude/settings.json`에 `"crossSessionInbound": "accept"`.**
   기본값에서는 Claude Code가 "신원 미상 발신자 + 프롬프트를 건너뛰는 세션"
   조합을 권한 상승으로 보고 peer 메시지를 **보류(held)**한다 — 소켓 전송은
   성공하지만 세션엔 안 들어가고 트랜스크립트에만 남는다. `accept`로 바꾸면
   바로 전달된다. (전역 설정: 이후 모든 세션에 적용. repo/managed 설정이
   `hold`면 그쪽이 우선한다.)
2. **세션을 `--dangerously-skip-permissions`(또는 신뢰 폴더 + `acceptEdits`)로
   시작.** peer 메시지는 네이티브 도구 권한 프롬프트를 못 닫는다 — 텔레그램에서
   "yes"를 보내도 그 다이얼로그는 안 닫힌다. 프롬프트가 아예 안 뜨게 해야 한다.

작업 지시 자체는 정상 처리되지만, Claude는 peer 메시지를 낮은 신뢰도로 취급해서
권한·설정 변경 같은 민감한 요청은 거절할 수 있다.

### 토픽 제목

Claude Code가 세션에 붙인 제목(`ai-title`)을 그대로 가져온다. `Stop` 훅이
트랜스크립트에서 읽어 실어보내고 브로커가 토픽 이름으로 한 번 설정한다. 제목이
나오기 전까지는 `<디렉터리> …`. `/title <text>`로 언제든 덮어쓴다. (API 키 불필요.)

### 세션 종료 / 정리

| 상황 | 방법 |
|---|---|
| 한 세션만 | 그 토픽에서 `/close` |
| 끝난 세션 일괄 | `bridge prune` (`status=ended`인 것) |
| 전부 | `bridge prune --all` (`-y`로 확인 생략) |
| 세션에서 `/exit` | `SessionEnd` 훅 → 기본은 상태만 `ended` 표시, **토픽은 남김** |
| `/exit` 시 토픽도 삭제 | `config.json`에 `"delete_topic_on_end": true` → 브로커 재시작 |

## 설정

`bridge setup`이 `~/.claude/bridge/config.json`을 쓴다:

| 키 | 기본값 | 의미 |
|---|---|---|
| `bot_token` | – | 텔레그램 봇 토큰 |
| `chat_id` | – | 슈퍼그룹 ID (음수, `-100…`) |
| `delete_topic_on_end` | `false` | 세션 종료 시 토픽도 삭제할지 |

환경 변수 오버라이드: `CLAUDE_TG_BOT_TOKEN`, `CLAUDE_TG_CHAT_ID`,
`CLAUDE_TG_DELETE_TOPIC_ON_END`. `CLAUDE_TG_BRIDGE_HOME`는 상태 디렉터리 전체를
옮긴다 (테스트에서 사용).

> 그룹 이름을 바꿔도 설정은 그대로다 — 라우팅은 `chat_id`와 `message_thread_id`
> 숫자만 쓴다. config를 다시 만져야 하는 건 그룹을 삭제하고 새로 만들 때뿐이다.

## 브로커 관리

```bash
uv run bridge status          # 브로커 + 세션별 상태
uv run bridge logs -f         # ~/.claude/bridge/state/broker.log tail
uv run bridge restart
uv run bridge prune           # 끝난 세션 토픽 + 상태 삭제 (--all / -y)
```

서비스로 돌리는 중이면 `bridge start/stop` 대신 `systemctl --user`로 제어한다
(pidfile 충돌):

```bash
systemctl --user restart claude-bridge-telegram.service   # 브로커 코드 수정 후
journalctl --user -u claude-bridge-telegram.service -f
./service/uninstall.sh                                    # 서비스 제거 (훅·상태는 안 건드림)
```

훅 스크립트는 매 호출마다 다시 읽히므로 훅을 고친 뒤엔 재시작이 필요 없다.

## 디렉터리 구조

```
<레포>/                          # 코드 — 아무 경로
  src/claude_bridge_telegram/    # 브로커, CLI, 텔레그램 클라이언트, inject, render, config
  hooks/                         # session_start / user_prompt_submit / stop / session_end / notification (stdlib 전용)
  service/                       # systemd 유닛 템플릿 + install.sh / uninstall.sh
  tests/                         # pytest (네트워크·실제 ~/.claude 안 씀)

~/.claude/bridge/                # 런타임 상태 (브로커 + 훅 공유)
  config.json
  state/{offset, broker.pid, broker.log}
  register/<sid>.json            # session_start → 브로커가 토픽 생성/갱신 (+ socket/token/pid)
  sessions/<sid>.json            # label, thread_id, status, titled, messaging_socket/token
  threads/<tid>                  # → sid
  inbox/<sid>.jsonl              # 주입 실패해 재시도 대기 중인 메시지
  outbox/<sid>/<ts>.json         # {"role","text"[,"ai_title"]} 대기 중인 아웃바운드
  end/<sid>.json                 # session_end → 브로커가 종료 처리
```

## 문제 해결

**`is_forum: None` / `the chat is not a forum`**
그룹에 Topics가 안 켜져 있다. 그룹 편집 → Topics → 켜기 → 저장.

**`not enough rights to create a topic`**
봇이 관리자지만 *주제 관리(Manage Topics)* 권한이 없다. 그룹 → 관리자 → 봇 →
주제 관리 켜기.

**`setup` 중 `0 update(s)` — 봇이 메시지를 못 받음**
privacy mode + 아직 관리자 아님, 또는 봇 합류 이전 메시지다. 관리자로 만든 뒤
*새* 메시지를 보낸다.

**토픽에 메시지를 보내도 세션에 안 들어감**
- 브로커가 떠 있나: `bridge status` / `systemctl --user status claude-bridge-telegram.service`
- `/status`로 소켓 상태 확인:
  - `ok` — 소켓은 정상. 그래도 안 들어가면 아래 "보류" 항목 확인.
  - `missing` — 세션이 재시작돼 pid가 바뀜. 세션에 프롬프트를 한 번 주면
    `SessionStart` 훅이 소켓을 갱신한다.
  - `unknown` — 그 세션이 `[uds-messaging]` 없이 떠서 미러 전용이다.
- **보류(held)** — 세션 트랜스크립트에 `Held peer message ... crossSessionInbound`
  가 보이면, `~/.claude/settings.json`에 `"crossSessionInbound": "accept"`가
  없는 것이다. 추가하면 이후 메시지는 바로 전달된다 (이미 보류된 건 다시 보내거나
  세션에서 승인).

**세션 응답이 그룹의 *General* 토픽에 뜸**
그 세션이 `bridge install-hooks` 이전에 시작돼 등록되지 않았다. 새 `claude`
세션을 시작하면 된다.

**`broker already running`**
stale pidfile이거나 진짜 실행 중이다. `cat ~/.claude/bridge/state/broker.pid`
확인 후, 아무것도 안 돌면 `rm` 하고 재시작.

## 개발

```bash
uv sync
uv run ruff check .
uv run pytest
```

자세한 규칙은 [`CLAUDE.md`](CLAUDE.md). 핵심:

- 훅은 **stdlib 전용·비블로킹**. 텔레그램은 브로커만 호출.
- `outbox` JSON 스키마를 바꾸면 `_bridge_common.queue_outbox`와
  `broker._read_outbox_item`를 같이 고칠 것.
- 봇 토큰은 `~/.claude/bridge/config.json`에만. 커밋 전 토큰 스캔.

## 이 머신 (`host`)

| 항목 | 값 |
|---|---|
| 코드 | `~/claude-bridge-telegram/` (`.venv/`, pyenv Python 3.12.14) |
| 상태 / 설정 | `~/.claude/bridge/`, `config.json` |
| 텔레그램 | 봇 `@example_bot`, 그룹 **"YourGroup"** (`chat_id -100XXXXXXXXXXX`), `delete_topic_on_end: true` |
| 브로커 | systemd `--user` 서비스, **enabled + linger** — 부팅 시 실행 |

```bash
systemctl --user restart claude-bridge-telegram.service       # 코드 변경 반영
journalctl --user -u claude-bridge-telegram.service -f        # 실시간 로그
~/claude-bridge-telegram/.venv/bin/bridge status              # 브로커 + 세션별 뷰
```

전체 제거:

```bash
./service/uninstall.sh
~/claude-bridge-telegram/.venv/bin/bridge uninstall-hooks
# 선택: loginctl disable-linger "$USER"; rm -rf ~/.claude/bridge
```
