# Band Archive — Discord 크롤링 프로젝트

## 프로젝트 개요

Discord 공개 채널 메시지를 정적 HTML로 크롤링하여 GitHub Pages로 게시하는 프로젝트입니다.

## 아키텍처

```
Discord Server → GitHub Actions (Cron 06:00 UTC)
  → Python crawler (discord.py async)
  → Jinja2 renderer
  → GitHub Pages (gh-pages 브랜치)
```

## 구현 단계

| 단계 | 내용 | 상태 |
|------|------|:----:|
| 1 | Discord Bot 생성 + Bot Token 획득 | ⏳ 사용자 작업 필요 |
| 2 | Bot을 서버에 초대 + 권한 설정 | ⏳ 사용자 작업 필요 |
| 3 | GitHub 저장소 생성 + Secrets 등록 | ⏳ 사용자 작업 필요 |
| 4 | GitHub Pages 활성화 | ⏳ 사용자 작업 필요 |
| 5 | Python 크롤러 구현 (`src/crawler.py`) | ✅ 완료 |
| 6 | Jinja2 HTML 렌더러 구현 (`src/renderer.py`) | ✅ 완료 |
| 7 | GitHub Actions 워크플로우 작성 (`.github/workflows/sync.yml`) | ✅ 완료 |
| 8 | Jinja2 템플릿 작성 (index/channel/thread HTML) | ✅ 완료 |
| 9 | 설정 + requirements.txt | ✅ 완료 |
| 10 | smoke test (로컬에서 수동 크롤링) | ⏳ 사용자 작업 필요 |

## 남은 설정 (사용자 작업)

### Discord Bot 생성
1. https://discord.com/developers/applications → 새 애플리케이션
2. Bot 탭 → Add Bot → 이름 설정
3. **Bot Permissions**:
   - `MESSAGE CONTENT INTENT` ✅
   - `GUILD MESSAGES INTENT` ✅
4. Token 복사 (보안 저장)

### Bot을 Discord 서버에 초대
```
https://discord.com/api/oauth2/authorize?client_id=<APP_CLIENT_ID>&permissions=102656+11264&scope=bot
```
Required Permissions:
- `VIEW_CHANNEL` (102656)
- `READ_MESSAGE_HISTORY` (11264)

### GitHub Secrets 설정
저장소 → Settings → Secrets → Actions:
| Name | Value |
|------|-------|
| `DISCORD_BOT_TOKEN` | Bot Token |
| `DISCORD_GUILD_ID` | 서버 ID (개발자 모드에서 복사) |

### 로컬 smoke test
```bash
cd C:/Users/user/goinfre/band-archive
pip install -r requirements.txt
export DISCORD_BOT_TOKEN=your_token
export DISCORD_GUILD_ID=your_guild_id
python -m src.crawler
python -m src.renderer
# docs/index.html 열어서 확인
```

---

## 파일 구조

```
band-archive/
├── README.md                      # 프로젝트 설명
├── requirements.txt               # Python 의존성
├── .github/
│   └── workflows/
│       └── sync.yml              # GitHub Actions (cron: 06:00 UTC)
├── src/
│   ├── __init__.py               # 패키지 초기화
│   ├── config.py                 # BOT_TOKEN, GUILD_ID 등 설정
│   ├── crawler.py                # Discord 메시지 크롤링 (discord.py async)
│   └── renderer.py               # Jinja2 HTML 렌더링
├── templates/
│   ├── index.html                # 채널 목록 페이지
│   ├── channel.html              # 채널 상세 (스레드 목록)
│   ├── thread.html               # 스레드 상세 (메시지 목록)
│   └── partials/
│       ├── message.html          # 메시지 컴포넌트
│       └── pagination.html       # 페이지네이션 컴포넌트
├── data/
│   └── guild_data.json           # 크롤링된 JSON 데이터 (git 추적)
└── docs/
    ├── Progress.md               # 진행상황 추적 (이 파일)
    └── index.html (렌더링 출력)   # GitHub Pages 루트
```

## 향후 개선 가능 항목

| 항목 | 설명 | 우선순위 |
|------|------|:--------:|
| 첨부파일 로컬 저장 | Discord CDN 대신 로컬 복사 | 낮음 |
| 증분 동기화 개선 | 마지막 메시지 ID 기반 업데이트만 가져오기 | 중간 |
| 검색 기능 | 클라이언트 측 JavaScript 검색 | 낮음 |
| 다국어 지원 | 템플릿 i18n 처리 | 낮음 |
| 아카이브된 스레드 | 아카이브된 스레드도 크롤링 | 중간 |

---

*마지막 업데이트: 2024-05-21*