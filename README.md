# Band Archive

Discord 공개 채널 메시지를 정적 HTML로 크롤링하여 GitHub Pages로 게시하는 프로젝트입니다.

## 아키텍처

```
Discord Server → GitHub Actions (Cron) → Python Crawler → Jinja2 Templates → GitHub Pages
```

## 기술 스택

- **크롤러**: Python 3.11+, discord.py (async)
- **템플릿**: Jinja2
- **호스팅**: GitHub Pages (gh-pages 브랜치)
- **CI/CD**: GitHub Actions (매일 06:00 UTC 자동 실행)

## 프로젝트 구조

```
band-archive/
├── .github/workflows/sync.yml   # GitHub Actions 워크플로우
├── src/
│   ├── config.py               # 설정 (Bot Token, Guild ID 등)
│   ├── crawler.py             # Discord 메시지 크롤링
│   └── renderer.py            # Jinja2 → HTML 렌더링
├── templates/
│   ├── index.html             # 채널 목록 首页
│   ├── channel.html          # 채널별 스레드 목록
│   ├── thread.html           # 스레드별 메시지 목록
│   └── partials/
│       └── message.html      # 메시지 컴포넌트
├── data/                      # 중간 JSON 데이터 (git 커밋)
├── docs/Progress.md           # 진행상황 추적
├── requirements.txt
└── README.md
```

## 설정 방법

### 1. Discord Bot 생성

1. [Discord Developer Portal](https://discord.com/developers/applications)에서 새 애플리케이션 생성
2. Bot 탭에서 "Add Bot" 클릭
3. **Required Intent** 활성화:
   - `MESSAGE CONTENT INTENT` ✅
   - `GUILD MESSAGES INTENT` ✅
4. Bot Token을 복사 (보안 저장)

### 2. Bot을 서버에 초대

초대 URL 생성:
```
https://discord.com/api/oauth2/authorize?client_id=<APPLICATION_ID>&permissions=102656+11264&scope=bot
```

권한:
- `VIEW_CHANNEL` (102656)
- `READ_MESSAGE_HISTORY` (11264)

### 3. GitHub Secrets 설정

저장소 → Settings → Secrets and variables → Actions에 추가:

| Secret Name | 값 |
|-------------|-----|
| `DISCORD_BOT_TOKEN` | Bot Token (1번에서 복사) |
| `DISCORD_GUILD_ID` | Discord Server ID |

### 4. GitHub Pages 활성화

저장소 → Settings → Pages:
- Source: `gh-pages` 브랜치

### 5. 수동 실행 (선택)

GitHub Actions → "Sync Discord" → "Run workflow"로 수동 트리거 가능

## 출력 구조 (GitHub Pages)

```
/ (index.html) — 채널 카테고리별 목록
├── channels/
│   └── {channel_id}/index.html — 해당 채널의 스레드 목록
└── threads/
    └── {thread_id}/index.html — 해당 스레드의 메시지 목록
```

## 라이선스

MIT License