# 쇼케이스(Feed) 폴리싱 핸드오프 문서 (다음 세션/다른 AI용)

이 문서는 **새 대화창에서 다른 동료 AI가 바로 코딩을 시작**할 수 있도록, 프로젝트 개요/현재 상태/이번까지 구현된 것/운영·배포 전제/검수 체크리스트/다음 작업 후보를 **최대한 구체적으로** 정리한 문서입니다. [[memory:12236647]]

---

## 1) 프로젝트 개요(이 프로젝트는 무엇인가)

### 무엇을 하는 서비스인가?
- **ComfyUI를 이미지 생성 엔진**으로 사용하고,
- 그 앞단에 **FastAPI 서버 + 웹 UI(HTML/JS/CSS)**를 붙여,
- 여러 사용자가 동시에 사용할 수 있게 **Job 큐/취소/진행률/개인 갤러리/쇼케이스(공유 피드)**를 제공하는 내부 베타 서비스.

### 핵심 구조(요약)
- 로그인 대신 **`anon_id` 쿠키**로 사용자 구분
- 생성 요청은 즉시 실행이 아니라 **Job 큐 등록 → 백그라운드 처리**
- 결과/입력/컨트롤 이미지는 DB가 아니라 **파일 기반(sidecar JSON + thumb)** 저장
- 운영 데이터(`outputs/`, `db/app_data.db`)는 유지하며 기능 추가는 **테이블 자동 생성/마이그레이션(있으면 스킵)** 방식

---

## 2) 개발/배포 운영 전제(매우 중요)

- 개발 PC와 서버 PC가 분리되어 있고, 배포는 **코드만 복사-붙여넣기**로 진행 예정 [[memory:12313212]].
- 서버에서 **절대 덮어쓰면 안 되는 것** [[memory:12313212]]
  - `outputs/` (운영 이미지 데이터)
  - `db/` (특히 `db/app_data.db`)
  - `venv/`
  - `logs/` (가능하면 유지)

---

## 3) 현재 사용자 UX(페이지 흐름)

- **랜딩**: `/` → `/feed`로 303 리다이렉트
- **쇼케이스(피드)**: `/feed`
- **이미지 생성**: `/create`
- 좌측 상단 네비게이션은 **탭 2개(쇼케이스 / 이미지 생성)**만 사용(이동 수단을 통일)

관련 파일:
- `templates/partials/sidebar.html`: 탭 2개 UI (`current_page`로 active 표시)
- `app/main.py`: `/create`, `/feed` 페이지 렌더링 시 `current_page` 전달

---

## 4) 쇼케이스(Feed) 저장 구조

### 4.1 파일 저장(피드 전역 복사본)
- Active:
  - `outputs/feed/YYYY/MM/DD/{post_id}.png`
  - `outputs/feed/YYYY/MM/DD/{post_id}.json`
  - `outputs/feed/YYYY/MM/DD/thumb/{post_id}.webp|jpg`
- Img2Img 입력 이미지(썸네일 포함):
  - `.../{post_id}_input.png`
  - `.../thumb/{post_id}_input.webp|jpg`
- Trash(삭제됨): `outputs/feed/trash/YYYY/MM/DD/...` 로 **파일 이동**
- 삭제 상태(trash) 파일은 **운영자 외 접근 금지(404)** (미들웨어)

관련 파일:
- `app/services/feed_media_store.py`
- `app/main.py` (trash 정적 접근 제어)

### 4.2 DB(SQLite)
DB: `db/app_data.db`

- `feed_posts`: 게시물 메타
- `feed_likes`: (레거시) 좋아요 토글 저장
- `feed_reactions`: (신규) 리액션 저장(유저당 1개)

관련 파일:
- `app/feed_store.py` (테이블 생성 + 로직)

---

## 5) API 요약(쇼케이스)

### 5.1 게시/조회
- `POST /api/v1/feed/publish`  
  - Body: `{ "image_id": "...", "author_name": "옵션" }`
  - 동작: 개인 갤러리 원본을 쇼케이스 경로로 복사(+Img2Img면 입력 썸네일 포함)

- `GET /api/v1/feed?page=&size=&sort=`  
  - `sort`: `newest`(기본) | `oldest` | `most_reactions`
  - `most_reactions` 동점 처리: **RANDOM()** (초기 0/동점일 때 섞이도록)
  - 응답 아이템에 포함:
    - `reactions` (각 리액션 카운트)
    - `my_reaction` (내가 누른 리액션)

- `GET /api/v1/feed/{post_id}` 상세  
  - `reactions`, `my_reaction`, `can_delete` 포함

### 5.2 리액션/삭제
- `POST /api/v1/feed/{post_id}/reaction`  
  - Body: `{ "reaction": "love|like|laugh|wow|fire" }`
  - 동작: 유저당 1개 반응 토글/교체
  - 호환: 기존 `feed_likes`는 **love(❤️)**로 합산/표시

- `POST /api/v1/feed/{post_id}/delete`  
  - 권한: 작성자(anon_id 동일) 또는 운영자(admin)
  - 동작: active → trash 파일 이동 + DB status 업데이트

관련 파일:
- `app/routers/feed.py`
- `app/feed_store.py`

---

## 6) 이번까지의 “쇼케이스 UI 폴리싱” 구현 내용(핵심)

### 6.1 레이아웃/탭 통일
- 쇼케이스(`/feed`)는 생성 페이지 레이아웃(입력 520px + 결과 1fr)을 쓰지 않도록 분리
- 좌측 상단 탭(쇼케이스/이미지 생성)만으로 이동 UX 통일

관련 파일:
- `templates/feed.html` (`main-content--feed`)
- `static/css/feed.css` (feed 전용 레이아웃)
- `templates/partials/sidebar.html` (탭 UI)
- `static/css/components.css` (탭 스타일)

### 6.2 브랜드 배너 이미지가 /feed에서도 항상 보이게
- 배너 적용 로직을 전역으로 분리해 모든 페이지에서 동일하게 표시

관련 파일:
- `static/js/brand_banner.js` (신규)
- `templates/base.html` (전역 로드)
- `static/js/app_config.js` (`APP_CONFIG.brand.url` 설정)

### 6.3 썸네일 카드 디자인 리뉴얼(레퍼런스 느낌)
- 카드가 이미지 중심 + 하단 그라데이션 오버레이(작성자/시간/리액션) 형태
- 썸네일 크기(그리드 최소 폭) 튜닝: 현재 **min 250px**

관련 파일:
- `static/css/feed.css`
- `static/js/feed.js` (카드 마크업)

### 6.4 리액션(바리에이션) 추가
- 기존 좋아요(❤️)만 → 5종 리액션: ❤️ 👍 😂 😮 🔥
- 카드/상세 모달 모두 리액션 표시 및 클릭 토글/교체

관련 파일:
- `app/feed_store.py`, `app/routers/feed.py`
- `static/js/feed.js`, `static/css/feed.css`

### 6.5 쇼케이스 상세 모달 연출
- 썸네일 클릭 시 **페이드 인/아웃 + 배경 블러**

관련 파일:
- `static/js/feed.js` (body 클래스 토글/스크롤 잠금)
- `static/css/feed.css` (opacity/transform/filter transition)

### 6.6 생성 직후 “결과 이미지 클릭” 시 정보/공유 버튼이 안 보이던 버그 수정
문제:
- 출력 영역의 결과 이미지를 클릭할 때 `openLightbox()`에 metaItem이 없어서
  워크플로우/시간/프롬프트/쇼케이스 공유 버튼이 비어 보임

해결:
- 생성 요청 시점에 요청 메타 스냅샷 저장
- 생성 완료 시 `image_path`에서 id 추출해 metaItem 구성
- 결과 이미지 클릭 시 그 metaItem을 넘겨 라이트박스 정보가 채워지도록 개선

관련 파일:
- `templates/index.html`

### 6.7 삭제 UI 폴리싱(디자인 유지 + 문구 최소화)
- 상세 모달의 삭제 버튼은 커스텀 확인 모달로 변경
- 확인 문구는 최종적으로 **“정말로 삭제하시겠습니까?”** 한 줄

관련 파일:
- `static/js/feed.js`

### 6.8 정렬 드롭다운 추가
- 상단 드롭다운으로 `최신순/오래된순/반응 많은 순` 선택
- 기본 `newest`, localStorage 저장(`feedSortKey`)

관련 파일:
- `templates/feed.html`
- `static/css/feed.css`
- `static/js/feed.js`
- `app/routers/feed.py`, `app/feed_store.py`

---

## 7) 중요한 파일 목록(최근 핵심 수정/추가)

### 새로 추가
- `static/js/brand_banner.js` (브랜드 배너 전역 적용)

### 최근 수정(쇼케이스 중심)
- `app/feed_store.py` (feed_reactions + 정렬 지원)
- `app/routers/feed.py` (sort 파라미터 + reactions 응답 + reaction 엔드포인트)
- `templates/feed.html` (정렬 드롭다운 + 캐시 버전)
- `static/js/feed.js` (리액션 UI/모달 연출/정렬 파라미터/삭제 confirm)
- `static/css/feed.css` (카드/모달/정렬 UI 스타일)
- `templates/partials/sidebar.html` (탭/명칭 쇼케이스)
- `static/css/components.css` (탭 스타일)
- `templates/base.html` (styles.css 버전 + brand_banner.js 포함)
- `templates/index.html` (라이트박스 meta 버그 수정, 쇼케이스 문구/아이콘 통일)
- `templates/admin.html` (관리 탭 명칭 “쇼케이스”)

---

## 8) 검수 체크리스트(사용자도 따라할 수 있는 버전)

### A. 이동/레이아웃
- `/` 접속 시 쇼케이스(`/feed`)가 뜬다
- 좌측 상단에 탭 2개가 있고, 탭으로 쇼케이스/이미지 생성 이동이 된다
- 쇼케이스 화면이 오른쪽 빈 공간 없이 넓게 보인다

### B. 쇼케이스 카드/상세
- 카드가 큰 썸네일 중심으로 보이고, 아래에 반응 버튼(5종)이 보인다
- 썸네일 클릭 시 모달이 페이드인 + 배경이 블러 처리된다

### C. 리액션
- ❤️ 👍 😂 😮 🔥 중 하나를 누르면 선택되고 다시 누르면 해제된다
- 다른 반응을 누르면 기존 반응이 교체된다(1개만 유지)

### D. 정렬
- 상단 드롭다운에서 정렬을 바꾸면 리스트가 다시 로드된다
- 기본은 최신순이고, 새로고침해도 선택이 유지된다

### E. 삭제
- 본인 게시물에서 “삭제” 버튼이 보인다
- 삭제 버튼을 누르면 “정말로 삭제하시겠습니까?” 확인 창이 뜬다
- 삭제 후 쇼케이스 목록에서 사라진다

### F. 이미지 생성 페이지 결과 클릭 버그
- 이미지 생성 직후 결과 이미지를 클릭하면
  워크플로우/시간/프롬프트/쇼케이스 공유 버튼이 정상 표시된다

---

## 9) 다음 세션 작업 후보(우선순위/아이디어)

### 9.1 정렬 안정성 개선(선택)
- 현재 `most_reactions`는 동점이면 `RANDOM()`이라 페이지 이동 시 순서가 흔들릴 수 있음
- 개선안:
  - 동점일 때만 `published_at DESC` 같은 안정 정렬을 기본으로 두고,
  - “랜덤 섞기”는 별도 옵션으로 제공하거나,
  - 서버에서 하루 단위 seed를 만들어 “하루 동안은 랜덤이 고정”되게 만들기

### 9.2 쇼케이스 Featured(추천) 기능(나중에 요청 예정)
- `feed_posts`에 `featured_rank` 추가(간단) 또는 별도 `feed_featured` 테이블(기획전/기간)
- Admin에서 토글/순서 조정 → 쇼케이스 상단 고정 노출

### 9.3 UX 자잘한 폴리싱
- 상대시간(“몇 분 전”) 표기
- 로딩 스켈레톤(정렬 변경/더 보기 로딩 시)
- 리액션 클릭 시 토스트/실패 메시지(현재는 alert 기반)
- 모달 내 정보 레이아웃 미세 조정(프롬프트 복사 토스트 등)

---

## 10) 배포 체크리스트(서버 PC)

1) ComfyUI 준비(필수): 커스텀 노드 requirements 설치/재시작/노드 로드 확인
2) FastAPI 코드 배포
   - `outputs/`, `db/`, `venv/`, `logs/`는 **절대 덮어쓰지 않기** [[memory:12313212]]
3) 스모크
   - `/feed` 로딩, 정렬 변경, 리액션 클릭
   - `/create` 생성 1회 → 결과 클릭 시 정보 표시
   - 공유/삭제/관리자 화면 확인


---

## 11) (추가) 2025-12-17 후반 세션 반영 사항 (동료 AI용 업데이트)

이번 세션에서 “쇼케이스” 자체 기능을 더 만든 것은 아니지만, **운영/UX 측면에서 중요한 버그 수정 + 생성 페이지 UI 개선**이 추가로 들어갔습니다.

### 11.1 `/admin` 접속이 JSON만 보이던 문제 수정 (BasicAuth 팝업 복구)
증상:
- `/admin` 접속 시 브라우저가 **아이디/비밀번호 팝업을 띄우지 않고**
  `{"detail":"Not authenticated"}` 같은 JSON만 노출됨

원인:
- `app/main.py`의 전역 `HTTPException` 핸들러가
  `WWW-Authenticate` 헤더를 포함한 **원래 응답 헤더를 제거**하고 JSON만 반환했음

해결:
- `app/main.py`에서 `HTTPException` 처리 시 `exc.headers`를 **그대로 전달**하도록 수정

관련 파일:
- `app/main.py`

검수:
- 서버 재시작 후 `/admin` 접속 시 브라우저 BasicAuth 팝업이 떠야 함

### 11.2 이미지 생성(/create) 화면의 “갤러리 슬라이드 버튼” 존재감 개선
요청/배경:
- 클로즈드 베타 피드백: “갤러리 슬라이드 버튼이 너무 안 보여서 존재를 몰랐다”
- 제약: **텍스트는 붙이지 않음(아이콘만 유지)**, PC 우선 + 모바일도 고려

개선 내용:
- 버튼을 화면 가장자리의 **‘손잡이(tab)’** 형태로 변경
  - 크기/대비/그림자 강화
  - 화면 밖으로 절반 나가 있던 형태(실제 보이는 면적이 너무 얇았음)를 개선
- **첫 1회 온보딩 말풍선** 추가
  - “여기서 갤러리를 열 수 있어요”가 잠깐 뜸
  - 사용자가 버튼을 누르거나 말풍선을 클릭하면 다시 안 뜨도록 처리(localStorage)

관련 파일:
- `templates/partials/gallery_panel.html` (`#gallery-toggle`, `#gallery-panel`)
- `templates/index.html` (갤러리 드로어 토글 + 온보딩 말풍선 로직)
- `static/css/components.css` (`.gallery-toggle` 손잡이 스타일, `.gallery-toggle-hint`)

참고(온보딩 표시 여부):
- localStorage 키: `galleryDrawerHintSeen:v1`
  - 테스트를 반복하려면 브라우저 개발자 도구에서 해당 키를 삭제하면 다시 노출됨

---

## 12) 다음 세션에서 진행할 “쇼케이스 사용자 UX/폴리싱” 5종 (요청 확정)

아래 5가지는 “골격 이후 실제 사용에서 자주 나오는 빈틈”을 메우는 작업입니다.

### 12.1 피드 빈 상태(0개) UX 추가
- 목표: 게시물이 없을 때도 “무엇을 하면 되는지”가 보이게
- 예: “아직 공유된 이미지가 없어요” + “이미지 생성으로 이동” CTA
- 관련 파일(예상): `templates/feed.html`, `static/js/feed.js`, `static/css/feed.css`

### 12.2 네트워크 실패/느림 시 안내 개선(alert → 토스트/배너)
- 목표: alert 대신 화면 상단/하단에 작은 안내(재시도 유도)
- 관련 파일(예상): `static/js/feed.js`, (공통 토스트 컴포넌트는 `static/css/components.css`/`static/js/*`로 분리 추천)

### 12.3 정렬 안정성 개선 (`most_reactions` 동점 랜덤으로 흔들림)
- 목표: “반응 많은 순”에서 페이지 이동/새로고침 시 순서가 너무 흔들리지 않게
- 개선안(예시):
  - 1차: reactions DESC
  - 2차: published_at DESC (안정)
  - “랜덤 섞기”는 별도 옵션으로 분리(선택)
- 관련 파일(예상): `app/feed_store.py`, `app/routers/feed.py`, `static/js/feed.js`

### 12.4 성능/체감 개선(썸네일 많아질 때)
- 목표: 로딩 체감 개선
- 후보:
  - 이미지 `loading="lazy"` 적용(가능한 위치에)
  - “더 보기/정렬 변경” 시 스켈레톤 또는 로딩 표시
- 관련 파일(예상): `static/js/feed.js`, `static/css/feed.css`

### 12.5 상세 모달 접근성/조작감(특히 모바일) 보강
- 목표: 닫기 버튼 터치 영역, 포커스/스크롤 처리, 키보드 조작 등 안정화
- 관련 파일(예상): `static/js/feed.js`, `static/css/feed.css`

