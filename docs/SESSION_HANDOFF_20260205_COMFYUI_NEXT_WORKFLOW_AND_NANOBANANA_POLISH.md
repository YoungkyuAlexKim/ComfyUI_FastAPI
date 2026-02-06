## 다음 세션 인계 문서 — NanoBanana 폴리싱 마무리 + EXP 뱃지 + ComfyUI img2img 다운스케일(1536) + 다음 작업: “ComfyUI 기본 txt2img 워크플로우 1개 추가” (2026-02-05)

대상 저장소: `c:\Works\ComfyUI_FastAPI`  
환경: Windows / FastAPI + Jinja 템플릿 프론트 (`templates/index.html` 내 JS 큼)  

이 문서는 **다음 세션(동료 AI)**가 초반에 코드베이스 탐색으로 토큰을 낭비하지 않도록, 아래 내용을 “바로 작업 가능한 수준”으로 정리합니다.

- 이번 세션에서 반영된 변경(나노바나나/ComfyUI/프론트 UX)
- 현재 동작 규칙(특히 숨김 레퍼런스/다운스케일/뱃지)
- 다음 세션 확정 작업: **ComfyUI provider의 “기본 txt2img 워크플로우 1개” 추가**

---

## 0) 큰 그림(관련 파일 위치)

- **워크플로우 설정(중심)**: `app/workflow_configs.py`의 `WORKFLOW_CONFIGS`
- **워크플로우 목록 API**: `app/routers/workflows.py` → `GET /api/v1/workflows`
- **생성 라우팅(ComfyUI vs Google)**: `app/services/generation.py`
  - `provider == "google"` → NanoBanana(Google Gemini) 호출
  - 그 외(기본) → ComfyUI 호출
- **Google 프롬프트 합성**: `app/services/google_nano_banana.py`의 `build_google_prompt()`
- **프론트(핵심)**: `templates/index.html`
- **워크플로우 배너 매핑(프론트 설정)**: `static/js/app_config.js`의 `window.APP_CONFIG.banners.map`

---

## 1) 이번 세션에서 구현/변경된 핵심

### 1.1 ComfyUI img2img 입력 이미지 다운스케일(긴 변 1536 상한)

배경: NanoBanana 출력처럼 큰 이미지(예: 2752×1536, 2048×2048)를 ComfyUI img2img로 넣으면 속도가 크게 느려짐.

정책:
- **비율 유지**
- **긴 변(max side) 1536px 상한**
- 원본 파일은 보존, **ComfyUI로 업로드할 bytes만 축소**

구현:
- `app/services/generation.py`
  - `_maybe_downscale_img2img_input_for_comfy()` 추가: PNG bytes를 열어 필요 시 1536 상한으로 리사이즈 후 PNG bytes 반환
  - ComfyUI img2img 입력 업로드 직전에 위 함수를 호출
  - “이미 ComfyUI input에 있던 파일(파일명 패스스루/사전 업로드)”도:
    - 로컬(`COMFY_INPUT_DIR`) 또는 ComfyUI `/view?type=input`로 bytes를 가져와
    - 리사이즈 후 “job 전용 임시 파일명”으로 다시 업로드해 사용
  - 작업 종료 후 기존 cleanup 로직으로 임시 업로드 파일 삭제

메타 기록:
- `app/services/media_store.py`의 `_save_image_and_meta()` 메타에
  - `comfy_img2img_input_downscale` 필드 추가
  - 원본/축소 해상도, resized 여부 등이 기록됨

---

### 1.2 outputs/global/characters는 “운영 데이터지만 커밋 허용”

`.gitignore` 변경:
- `outputs/`는 기본 ignore 유지
- 단, `outputs/global/characters/**`만 예외로 **git 추적 가능**

파일: `.gitignore`

주의:
- `db/app_data.db`는 로컬 데이터가 섞이므로 커밋 제외 권장(현 세션에서도 변경됨)

---

### 1.3 NanoBanana(Pro) 배너 연결

`static/js/app_config.js`의 `window.APP_CONFIG.banners.map`에 NanoBanana 계열 배너가 매핑됨.
- `NanoBanana_ExpressionPortraitSheet` → `img_banner_Banana_FacialExpressions.png`
- `NanoBanana_Relight` → `img_banner_Banana_Relight.png`
- `NanoBanana_StoryboardCutboard` → `img_banner_Banana_StoryBoard.png`
- `NanoBanana_TurnaroundSheet` → `img_banner_Banana_TurnAround.png`
- `NanoBanana_WhatsNextVariations` → `img_banner_Banana_WhatsNext.png`
- `NanoBanana`/`NanoBanana_Img2Img` → `img_banner_Banana_Basic.png`

추가 배너(이번 세션 추가 파일):
- `static/img/banner/img_banner_Banana_CJKCharacterSheet.png`

---

### 1.4 새 NanoBanana “숨김 레퍼런스(서버 전용) + 컨셉 한 줄” 워크플로우 추가

워크플로우:
- ID: `NanoBanana_ChainsawJuiceKingCharacter`
- 성격: **실험적(특수 목적)**, 범용성 낮음
- 사용자 UX: “컨셉 한 줄 입력”만 노출 (프롬프트는 비워두고 placeholder로 유도)

숨김 레퍼런스 파일(서버만 읽음):
- 경로: `app/resources/refs/chainsaw_juice_king_reference.png`
- 폴더 안내: `app/resources/refs/README.md`

설정 위치:
- `app/workflow_configs.py`
  - `google_hidden_reference_images`: `["app/resources/refs/chainsaw_juice_king_reference.png"]`
  - `ui.badges`: `["EXP"]` (실험 표시)
  - `ui.generateLabel`: “캐릭터 시트 만들기”
  - `ui.showPromptTranslate`: False (한글 컨셉이 더 잘 먹히는 경우를 반영)
  - `style_prompt`: 한국어로 “작업목표/규칙”만 담고, 컨셉/아웃풋은 사용자 입력과 합쳐 최종 프롬프트를 구성

서버 처리(숨김 레퍼런스 → 자동 image-edit 전환):
- `app/services/generation.py`
  - google provider + txt2img에서도
  - `wf_cfg.google_hidden_reference_images`가 있으면
  - 해당 이미지를 PNG bytes로 로드해 `generate_image_edit()`로 자동 전환

프롬프트 최종 형태(의도):
- 시스템(숨김): “작업목표/규칙”
- 사용자 입력: `컨셉 : ...` 한 줄만
- 출력 지시: `아웃풋 : 64개/8x8` 고정
- 컨셉이 비어있으면 기본값: **“일상 캐주얼 스타일”**

---

### 1.5 EXP(실험) 뱃지 표시(워크플로우 리스트 + 선택된 워크플로우명)

목표: 실험 워크플로우를 사용자가 “안정 기능과 구분”할 수 있게 하기.

구현:
- `app/workflow_configs.py`: 각 워크플로우 `ui.badges`에 문자열 배열로 지정(예: `["EXP"]`)
- `templates/index.html`:
  - 워크플로우 리스트 렌더링에서 `ui.badges`를 읽어 뱃지 표시
  - “선택된 워크플로우”/상단 제목에도 inline 뱃지 표시
  - 긴 제목이 잘릴 수 있어 **뱃지 크기 축소(아래 CSS 참고)** 및 title tooltip(hover) 추가
- `static/css/components.css`: `.wf-badge`, `.wf-badge--exp` 스타일(작게)

---

### 1.6 (중요 UX) 새로고침 시 img2img 입력 이미지 슬롯 초기화

문제: 이전에는 입력 이미지가 `localStorage`에 저장되어 새로고침 후에도 슬롯에 남아 있었음.

해결:
- `templates/index.html` 초기 로드 시점에 아래 키를 삭제:
  - `localStorage.inputImageId`
  - `localStorage.inputImageIds`

효과:
- 새로고침/재접속 시 img2img 입력 슬롯은 항상 “빈 상태”로 시작

---

### 1.7 “기본 프롬프트 자동 채움” 제거 → placeholder 안내로 전환(대부분 워크플로우)

정책:
- 사용자 입력칸은 **기본값을 넣지 않는다**
- 대신 “무엇을 입력해야 하는지”를 placeholder로 안내한다

반영:
- `app/workflow_configs.py`
  - `NanoBanana` 기본 워크플로우: `default_user_prompt`를 빈 값으로 변경 + `ui.userPromptPlaceholder` 추가
  - 여러 ComfyUI 워크플로우(자연어/태그/Img2Img 포함)도 `default_user_prompt`를 비우고 `ui.userPromptPlaceholder`를 추가/정리

---

### 1.8 NanoBanana(Google)에서는 seed UI 숨김

현재 통합에서는 NanoBanana 호출 시 Google API에 seed를 전달하지 않으므로, 사용자가 seed를 바꿔도 재현성이 보장되지 않음.

해결:
- `templates/index.html`의 `applySeedVisibilityForWorkflow()`에서
  - `provider === "google"`이면 seed row를 숨김

---

## 2) 다음 세션 확정 작업: “ComfyUI 기본 txt2img 워크플로우 1개 추가”

목표:
- NanoBanana가 아닌 **ComfyUI provider 기반의 기본 txt2img 워크플로우** 1개를 추가
- 사용자에게는 기본 프롬프트를 미리 채우지 않고 **placeholder로만 안내**

필수 작업 체크리스트:
1) `workflows/<NEW_WORKFLOW_ID>.json` 추가(또는 기존 JSON 기반 복사)
2) `app/workflow_configs.py`의 `WORKFLOW_CONFIGS`에 `<NEW_WORKFLOW_ID>` 엔트리 추가
3) (선택) 배너가 필요하면 `static/js/app_config.js`의 `banners.map`에 매핑 추가 + `static/img/banner/`에 이미지 추가

추가 구현 힌트(가장 빠른 길):
- `WORKFLOW_CONFIGS`에서 기존 ComfyUI txt2img 템플릿을 참고
  - 예: `BasicWorkFlow_PixelArt`, `BasicWorkFlow_MKStyle` (현재 hidden=True인 것들이 있음)
- 새 워크플로우 config에 최소로 필요한 키:
  - `display_name`, `description`
  - `default_user_prompt`: `""` (비워두기)
  - ComfyUI 노드 매핑: `prompt_node`, `negative_prompt_node`(있으면), `seed_node`, `latent_image_node`
  - `style_prompt`, `negative_prompt`
  - `sizes` 또는 `size_nodes`(워크플로우 구조에 따라)
  - `ui`: `{ icon, showPromptTranslate, templateMode, userPromptPlaceholder, ... }`

주의(자주 실수하는 포인트):
- 프론트는 워크플로우별 placeholder를 `ui.userPromptPlaceholder`에서 가져옴
- seed row는 google provider에만 숨김이므로 ComfyUI에는 계속 표시됨(정상)
- `GET /api/v1/workflows`는 provider=google 워크플로우를 포함해 목록을 반환합니다.

---

## 3) 빠른 테스트 시나리오(다음 세션 시작 체크리스트)

1) 서버 실행 후 `/create` 접속
2) 워크플로우 리스트에서:
   - `NanoBanana_ChainsawJuiceKingCharacter`에 **EXP 뱃지**가 붙는지 확인
3) 새로고침(F5) 후 img2img 입력 이미지 슬롯이 **빈 상태**인지 확인
4) ComfyUI img2img 워크플로우에서 큰 이미지를 입력으로 넣고 실행해:
   - 결과 메타(json)에 `comfy_img2img_input_downscale` 기록이 남는지 확인
5) NanoBanana 워크플로우에서 seed 입력 UI가 **숨겨져 있는지** 확인
6) 기본 프롬프트 자동 채움이 사라지고 placeholder만 보이는지 확인

---

## 4) 커밋/운영 주의사항

- `db/app_data.db`는 로컬 데이터이므로 커밋 제외 권장
- `outputs/global/characters/**`는 운영 데이터이지만, 정책상 커밋 가능하도록 `.gitignore` 예외가 적용됨

