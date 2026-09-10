# claude-bridge-telegram

텔레그램에서 Claude Code를 돌린다. 세션마다 그룹 안에 방(토픽)이 하나 생기고,
프롬프트와 응답이 거기로 오간다. 자리에 없어도 폰으로 이어서 작업할 수 있다.

## 뭐가 좋은가

- **세션 하나에 토픽 하나.** 텔레그램 그룹의 Topics 기능을 그대로 쓴다. 세션을
  다섯 개 돌려도 대화가 안 섞이고, 토픽 이름은 Claude가 대화 내용을 보고 알아서
  붙인다. 그룹 하나로 모든 세션을 관리한다.
- **자리를 떠도 이어진다.** 데스크탑에서 시작한 작업을 폰에서 확인하고 지시한다.
  마이그레이션이나 큰 리팩터처럼 오래 걸리는 작업을 이동 중에도 붙잡고 갈 수 있다.
- **터미널에 안 붙어도 된다.** 터미널이든 Orca든 Claude Desktop이든, 어디서 띄운
  세션이든 붙는다. tmux도 PTY 트릭도 필요 없다. Claude Code 2.x에 들어 있는
  세션 소켓을 그대로 쓴다.
- **설정은 세 줄이다.** `bridge setup`, `bridge install-hooks`, `./service/install.sh`.
  웹서버도 DB도 없다. 데몬 하나와 훅 몇 개가 파일로 대화한다.
- **읽을 만하게 나온다.** 마크다운은 텔레그램 서식으로 바뀌고 표는 폭을 맞춘다.
  Claude가 작업 중인지, 입력을 기다리는지도 표시된다.
- **군더더기가 없다.** 봇 토큰은 로컬 설정 파일에만 있고, 훅은 표준 라이브러리만
  쓴다. 밖으로 나가는 건 텔레그램 API 호출뿐이다.

토픽 하나는 대충 이렇게 보인다.

```
🧑  로그인하면 홈이 아니라 login 페이지로 리다이렉트돼. 봐줘
🤖  auth 미들웨어가 세션 없을 때 /login으로 보내는데, 토큰 갱신 중인
    요청도 "세션 없음"으로 걸립니다. 갱신 핸들러를 먼저 태우면 됩니다.
🧑  그렇게 고쳐줘
🔧  작업 중 (14s)
🤖  middleware/auth.ts:23 에 갱신 토큰 예외를 넣었습니다. 로컬에서
    로그인하니 홈 그대로 유지됩니다.
```

## 요구 사항

- Claude Code 2.x (`[uds-messaging]` 소켓이 있는 버전)
- [uv](https://docs.astral.sh/uv/)
- Topics를 켠 텔레그램 슈퍼그룹과 봇 하나

## 설치

### 텔레그램 (처음 한 번)

1. [@BotFather](https://t.me/BotFather)에서 `/newbot`으로 봇을 만들고 토큰을 받는다.
2. 슈퍼그룹을 만들고 그룹 편집에서 Topics를 켠다.
3. 봇을 그룹에 넣고 관리자로 올린다. 관리자 권한 화면에서 "주제 관리(Manage
   Topics)"를 직접 켜야 한다. 관리자여도 기본은 꺼져 있다.
4. 봇이 관리자가 된 다음 그룹에 아무 메시지나 하나 보낸다. 그 전 메시지는 봇이
   못 본다.

### 브리지

```bash
git clone <이 저장소>
cd claude-bridge-telegram
uv sync

uv run bridge setup           # 봇 토큰 입력. ~/.claude/bridge/config.json 생성
uv run bridge install-hooks   # ~/.claude/settings.json에 훅 등록. 기존 파일은 백업됨
./service/install.sh          # 브로커를 systemd --user 서비스로 등록
```

마지막으로 `~/.claude/settings.json`에 한 줄 넣는다. 이게 없으면 텔레그램에서 보낸
메시지가 세션까지 가지 못한다. 이유는 [권한](#권한)에 있다.

```json
"crossSessionInbound": "accept"
```

서비스 없이 잠깐만 써 볼 거면 `uv run bridge start` / `stop`으로 돌려도 된다.
레포를 옮겼다면 옛 위치에서 `bridge uninstall-hooks`를 하고, 새 위치에서
`uv sync && uv run bridge install-hooks && ./service/install.sh`를 다시 실행한다.

### 세션 시작

```bash
claude --dangerously-skip-permissions
```

그룹에 `<디렉터리>-<세션ID>` 토픽이 생긴다. 이 플래그가 필요한 이유는
[권한](#권한)에 있다.

## 사용

프롬프트(`🧑`)와 응답(`🤖`)이 토픽에 그대로 올라온다. 마크다운은 텔레그램 서식
으로 바뀌고, 표는 폭을 맞춘 고정폭 블록이 된다.

토픽에 메시지를 쓰면 몇 초 안에 세션에 들어간다. Claude가 작업 중이면 현재 턴이
끝난 뒤에 처리된다고 알려준다.

세션이 입력을 기다리면(`AskUserQuestion` 같은 경우) `🔔`로 표시된다. 답은 토픽에
그냥 쓰면 된다.

### 토픽 명령

| 명령 | 하는 일 |
|---|---|
| `/status` | 세션 상태, 작업 중 여부, 소켓 연결, 작업 디렉터리 |
| `/title <text>` | 토픽 이름 바꾸기. 기본값은 Claude가 붙인 제목 |
| `/sessions` | 전체 세션 목록 |
| `/exit` | 이 토픽 삭제. 로컬 세션 기록은 남는다 |
| `/help` | 명령 목록 |

`/exit`는 토픽만 지운다. 끝난 세션 기록까지 정리하려면 `uv run bridge prune`을
쓴다. `--all`은 전부, `-y`는 확인 생략.

## 설정

`bridge setup`이 만드는 `~/.claude/bridge/config.json`:

| 키 | 기본값 | 뜻 |
|---|---|---|
| `bot_token` | – | 텔레그램 봇 토큰 |
| `chat_id` | – | 슈퍼그룹 ID |
| `delete_topic_on_end` | `false` | 터미널에서 세션이 끝날 때 토픽도 지울지 |

환경 변수 `CLAUDE_TG_BOT_TOKEN`, `CLAUDE_TG_CHAT_ID`,
`CLAUDE_TG_DELETE_TOPIC_ON_END`로 덮어쓸 수 있다.

## 브로커 관리

```bash
uv run bridge status      # 브로커와 세션 상태
uv run bridge logs -f     # 로그
uv run bridge prune       # 끝난 세션 정리
```

서비스로 돌리는 중이면 `start` / `stop` 대신 systemd를 쓴다.

```bash
systemctl --user restart claude-bridge-telegram.service   # 브로커 코드를 고친 뒤
journalctl --user -u claude-bridge-telegram.service -f
./service/uninstall.sh                                    # 서비스만 제거
```

훅은 매번 새로 읽히니 훅만 고쳤을 때는 재시작하지 않아도 된다.

## 권한

브로커가 넣는 메시지는 세션에 peer 메시지로 도착한다. 사람이 친 프롬프트가 아니라
다른 Claude 세션이 보낸 것으로 취급된다. 그래서 무인으로 돌리려면 두 가지가 필요
하다.

**`crossSessionInbound: accept`** 를 `~/.claude/settings.json`에 넣는다. 기본값
이면 Claude Code가 프롬프트를 건너뛰는 세션에 낯선 발신자가 메시지를 넣는 상황을
막고, 메시지를 보류한다. `accept`면 바로 전달된다.

**`--dangerously-skip-permissions`** 로 세션을 시작한다. 신뢰 폴더에 `acceptEdits`
를 걸어도 된다. peer 메시지는 도구 권한 창을 대신 눌러 주지 못하므로, 그 창이
아예 안 뜨게 해야 한다.

작업 지시는 정상으로 처리되지만, 권한이나 설정을 바꾸는 요청은 신뢰도가 낮아
세션이 거절할 수 있다.

## 작동 방식

훅은 세션 이벤트마다 `~/.claude/bridge/` 아래에 파일 하나를 쓰고 바로 끝난다.
표준 라이브러리만 쓰고 블로킹하지 않는다.

브로커는 텔레그램과 이야기하는 유일한 프로세스다. 토픽을 만들고, 응답을
내보내고, 세션 소켓으로 메시지를 넣는다.

Claude Code 2.x는 세션마다 유닉스 소켓을 연다(`$CLAUDE_CODE_MESSAGING_SOCKET`,
`$CLAUDE_CODE_MESSAGING_TOKEN`). `SessionStart` 훅이 이 값을 적어 두면 브로커가
거기 붙어 프롬프트 큐에 메시지를 넣는다.

더 자세한 구조와 기여 규칙은 [`CLAUDE.md`](CLAUDE.md)에 있다.

## 문제 해결

**`is_forum: None` 또는 `the chat is not a forum`**
그룹에 Topics가 안 켜져 있다. 그룹 편집에서 켠다.

**`not enough rights to create a topic`**
봇에게 "주제 관리" 권한이 없다. 그룹 관리자 설정에서 봇에게 켜 준다.

**`setup` 중에 `0 update(s)`**
봇이 아직 관리자가 아니거나, 관리자가 되기 전 메시지만 있다. 관리자로 만든 뒤
새 메시지를 보낸다.

**토픽에 써도 세션에 안 들어간다**
`bridge status`로 브로커가 떠 있는지 본다. `/status`의 소켓 값이 `missing`이면
세션이 재시작돼 pid가 바뀐 것이니, 세션에 프롬프트를 한 번 주면 다시 잡힌다.
`unknown`이면 그 세션에 `[uds-messaging]` 소켓이 없어 미러 전용이다. 세션
트랜스크립트에 `Held peer message`가 보이면 `crossSessionInbound: accept`가
빠진 것이다.

**응답이 그룹의 General 토픽에 뜬다**
그 세션이 `bridge install-hooks` 전에 시작됐다. 세션을 새로 연다.

**`broker already running`**
죽은 pidfile이 남은 것이다. `~/.claude/bridge/state/broker.pid`를 확인하고,
실제로 안 돌고 있으면 지운다.

## 개발

```bash
uv sync && uv run ruff check . && uv run pytest
```

규칙은 [`CLAUDE.md`](CLAUDE.md).
