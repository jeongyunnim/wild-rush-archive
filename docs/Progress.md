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

## 변경 이력

### 2026-05-21: UI 리디자인 (Tailwind CSS Dark Mode)

**변경된 파일:**
- `templates/index.html`
- `templates/channel.html`
- `templates/thread.html`

**주요 변경 사항:**

1. **프레임워크 전환**: Bootstrap 5 → Tailwind CSS (CDN)
2. **아이콘**: Lucide Icons (stroke-width: 1.5)
3. **폰트**: Inter (Google Fonts, 300/400/500/600 weights)
4. **디자인 스타일**: Linear/Stripe/Vercel 영감의 모던 다크 테마

**디자인 요소:**
- **색상 팔레트**: 커스텀 다크 컬러 (dark-50 ~ dark-900), Indigo 액센트
- **배경**: 그라데이션 (0a0f1a → 030712)
- **카드**: Glass morphism (backdrop-filter blur), 반투명 배경
- **테두리**: 미묘한 border (dark-500/20~30)
- **호버 효과**: 부드러운 트랜지션, 색상 변화, translateX 이동
- **반응형**: 모바일/데스크톱 대응

**index.html 변경점:**
- 길드 헤더: 아이콘 + 이름 + 설명 (rounded-2xl glass card)
- 카테고리 섹션: 폴더 아이콘 + 대문자 라벨
- 채널 카드: 해시 아이콘, 토픽, 스레드/메시지 수 배지
- 호버 시 translateX(4px) 애니메이션

**channel.html 변경점:**
- 브레드크럼: 홈 아이콘 + chevron 구분자
- 채널 헤더: gradient 아이콘 박스, 카테고리 표시
- 스레드 목록: 왼쪽 보더 라인, 날짜/작성자 정보
- 메시지 목록: 아바타 + 이름 + 타임스탬프 + 콘텐츠 + 첨부파일 + 리액션

**thread.html 변경점:**
- 브레드크럼: 3단계 (홈 → 채널 → 스레드)
- 스레드 헤더: git-branch 아이콘, 생성일/메시지 수
- 날짜 구분선: 가운데 배치, 양쪽 그라데이션 라인
- 메시지 카드: 스레드 시작 메시지 강조 (왼쪽 indigo 보더)
- 역할 배지, 리액션 스타일링
- Embed 카드 (왼쪽 보더 + 어두운 배경)

**제거된 요소:**
- 플로팅 다운로드 버튼
- 이모지 사용 (아이콘으로 대체)
- Bootstrap 관련 클래스

---

*마지막 업데이트: 2026-05-21*