# claude-bridge-telegram

Claude Code 세션을 텔레그램에서 조종하는 브리지. 세션마다 텔레그램 그룹에 **포럼
토픽**이 하나씩 생기고 — 프롬프트·응답이 그 토픽으로 흘러나오고, 토픽에 쓴
메시지는 돌고 있는 세션에 바로 주입된다 (턴 중이든 idle이든).

```
세션 ──훅──▶ 브로커 ──▶ 텔레그램 토픽
텔레그램 토픽 ──▶ 브로커 ──▶ 세션 (uds-messaging 소켓)
```

## 요구 사항

- Claude Code **2.x** (`[uds-messaging]` 소켓이 있는 버전)
- [uv](https://docs.astral.sh/uv/)
- 텔레그램 봇 + **Topics가 켜진 슈퍼그룹**

## 설치

### 1. 텔레그램 봇 + 그룹 (최초 1회)

1. [@BotFather](https://t.me/BotFather) → `/newbot` → 토큰 복사
2. 슈퍼그룹 생성 → **그룹 편집 → Topics 켜기**
3. 봇을 그룹에 추가 → **관리자로 승격**, 관리자 권한에서 **주제 관리(Manage
   Topics)**를 직접 켠다 (관리자라도 기본 꺼짐)
4. 봇이 관리자가 된 *뒤에* 그룹에 아무 메시지나 하나 보낸다

막히면 → [문제 해결](#문제-해결).

### 2. 브리지

```bash
git clone <이 저장소>
cd claude-bridge-telegram
uv sync

uv run bridge setup           # 봇 토큰 입력 → ~/.claude/bridge/config.json (chmod 600)
uv run bridge install-hooks   # ~/.claude/settings.json에 훅 등록 (자동 백업)
./service/install.sh          # 브로커를 systemd --user 서비스로 상시 실행
```

그리고 `~/.claude/settings.json`에 한 줄 추가한다. 없으면 텔레그램 메시지가 세션에
전달되지 않고 보류된다 ([권한](#권한) 참고):

```json
"crossSessionInbound": "accept"
```

> - 임시로만 쓸 땐 서비스 대신 `uv run bridge start` / `stop`.
> - 레포를 옮겼으면: 옛 위치에서 `bridge uninstall-hooks` → 새 위치에서
>   `uv sync && uv run bridge install-hooks && ./service/install.sh`.

### 3. 세션 시작

```bash
claude --dangerously-skip-permissions
```

`<디렉터리>-<세션ID>` 형태의 토픽이 그룹에 나타난다. 이후 그 세션의 대화가 토픽에
미러링되고, 토픽에 쓰는 메시지가 세션에 주입된다. (`--dangerously-skip-permissions`가
필요한 이유는 [권한](#권한).)

## 사용

- **미러링** — 프롬프트(`🧑`)·응답(`🤖`)이 토픽에 뜬다. 마크다운은 텔레그램 서식
  으로 변환되고 표는 정렬된 고정폭 블록이 된다.
- **주입** — 토픽에 메시지를 쓰면 몇 초 내로 세션에 들어간다. Claude가 작업 중이면
  `⏳ 작업 중 — 현재 턴이 끝난 뒤 처리됩니다`라고 알려준다.
- **알림** — 세션이 입력을 기다리면(`AskUserQuestion` 등) `🔔`로 표시된다. 답은
  토픽에 그냥 쓰면 프롬프트 큐에 들어간다.

### 토픽 명령

| 명령 | 효과 |
|---|---|
| `/status` | 상태, 작업 중 여부, 소켓 연결, cwd |
| `/title <text>` | 토픽 이름 변경 (기본값은 Claude가 붙인 제목) |
| `/sessions` | 전체 세션 목록 |
| `/exit` | 이 토픽 삭제. 로컬 세션 기록은 유지 (터미널 `/exit`과 같은 느낌) |
| `/help` | 명령 목록 |

### 정리

- `/exit` — 토픽만 삭제, 기록은 남음
- `uv run bridge prune` — 끝났거나 `/exit`한 세션 일괄 정리 (`--all` 전부, `-y` 확인 생략)

## 설정

`bridge setup`이 `~/.claude/bridge/config.json`을 만든다:

| 키 | 기본값 | 의미 |
|---|---|---|
| `bot_token` | – | 텔레그램 봇 토큰 |
| `chat_id` | – | 슈퍼그룹 ID |
| `delete_topic_on_end` | `false` | 터미널에서 세션 종료 시 토픽도 삭제할지 |

환경 변수로 덮어쓰기: `CLAUDE_TG_BOT_TOKEN`, `CLAUDE_TG_CHAT_ID`,
`CLAUDE_TG_DELETE_TOPIC_ON_END`.

## 브로커 관리

```bash
uv run bridge status      # 브로커 + 세션별 상태
uv run bridge logs -f     # 로그
uv run bridge prune       # 끝난 세션 정리

# systemd 서비스로 돌 때 (start/stop 대신):
systemctl --user restart claude-bridge-telegram.service   # 브로커 코드 수정 후
journalctl --user -u claude-bridge-telegram.service -f
./service/uninstall.sh                                    # 서비스만 제거
```

훅 스크립트는 매 호출마다 다시 읽히므로 훅을 고친 뒤엔 재시작이 필요 없다.

## 권한

브로커가 넣는 메시지는 세션에 **peer 메시지**(다른 Claude 세션발)로 도착한다 —
1인칭 유저 입력이 아니다. 그래서 무인 구동하려면 둘 다 필요하다:

1. **`crossSessionInbound: accept`** (`~/.claude/settings.json`) — 기본값에서는
   Claude Code가 "프롬프트를 건너뛰는 세션 + 신원 미상 발신자" 조합을 막아
   메시지를 **보류**한다. `accept`면 바로 전달된다.
2. **`--dangerously-skip-permissions`** (또는 신뢰 폴더 + `acceptEdits`) — peer
   메시지는 네이티브 도구 권한 다이얼로그를 못 닫는다. 프롬프트가 아예 안 뜨게
   시작해야 한다.

작업 지시는 정상 처리되지만, 권한·설정 변경 같은 민감한 요청은 peer 신뢰도 때문에
세션이 거절할 수 있다.

## 작동 방식

- **훅** (`hooks/`, stdlib 전용·비블로킹) — 세션 이벤트마다 `~/.claude/bridge/`
  아래에 작은 파일 하나 쓰고 즉시 종료.
- **브로커** (`bridge` 데몬) — 텔레그램과 통신하는 유일한 프로세스. 토픽 생성,
  응답 미러링, `[uds-messaging]` 소켓으로 메시지 주입. `getUpdates`를 독점하므로
  세션이 여러 개여도 경합이 없다.
- Claude Code 2.x는 세션마다 유닉스 소켓(`$CLAUDE_CODE_MESSAGING_SOCKET` +
  `$CLAUDE_CODE_MESSAGING_TOKEN`)을 연다. `SessionStart` 훅이 이 정보를 기록하고
  브로커가 접속해 메시지를 프롬프트 큐에 넣는다.

아키텍처 상세와 기여 규칙은 [`CLAUDE.md`](CLAUDE.md).

## 문제 해결

**`is_forum: None` / `the chat is not a forum`**
그룹에 Topics가 안 켜져 있다. 그룹 편집 → Topics → 켜기.

**`not enough rights to create a topic`**
봇에게 *주제 관리(Manage Topics)* 권한이 없다. 그룹 → 관리자 → 봇 → 주제 관리.

**`setup` 중 `0 update(s)`**
봇이 아직 관리자가 아니거나 합류 이전 메시지만 있다. 관리자로 만든 뒤 *새* 메시지를 보낸다.

**토픽에 써도 세션에 안 들어감**
- 브로커가 떠 있나: `bridge status`
- `/status`의 `socket` 값:
  - `missing` — 세션 재시작으로 pid가 바뀜. 세션에 프롬프트를 한 번 주면 갱신된다.
  - `unknown` — 그 세션이 `[uds-messaging]` 없이 떠서 미러 전용.
- 세션 트랜스크립트에 `Held peer message` → `crossSessionInbound: accept` 누락 ([권한](#권한)).

**응답이 그룹의 *General* 토픽에 뜸**
그 세션이 `bridge install-hooks` 이전에 시작됐다. 새 세션을 시작한다.

**`broker already running`**
stale pidfile. `cat ~/.claude/bridge/state/broker.pid` 확인 후 필요하면 `rm`.

## 개발

```bash
uv sync && uv run ruff check . && uv run pytest
```

규칙은 [`CLAUDE.md`](CLAUDE.md).
