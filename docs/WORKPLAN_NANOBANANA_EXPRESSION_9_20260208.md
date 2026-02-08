## 작업계획서: NanoBanana 입력 1장 → 표정 9개 시트

> 작성일: 2026-02-08  
> 대상 워크플로우: `NanoBanana_ExpressionPortraitSheet`  
> 목적: **입력 이미지 1장**을 identity reference로 사용하여, **표정 포트레이트 9개(3×3)** 를 “한 장의 시트 이미지”로 안정적으로 출력한다.

---

### 현재 파악된 현상(코드 기준)
- **워크플로우 정의 위치**: `app/workflow_configs.py`
  - `provider: "google"`
  - `google: { model: "gemini-3-pro-image-preview", mode: "image-edit" }`
  - `image_input` 존재(UI에서 “입력 이미지 필수”로 인지시키는 gate)
  - UI 스키마: `userPromptOptional: true`(스타일 힌트 선택 입력), `aspectOptions: ["square"]`, `expressionTool`에 9/4 프리셋
- **실행 경로**: `app/services/generation.py`
  - Google provider면 NanoBanana image-edit 호출
  - 입력 이미지는 `input_image_ids`(우선) 또는 `input_image_id`(fallback)로 resolve
  - 저장은 `app/services/media_store.py`를 통해 `outputs/users/<anon>/...`에 PNG+meta로 기록

---

### 목표 동작(수용 기준)
- **입력**: 사용자 입력 이미지 1장(uploads → inputs 보관함 id)
- **스타일(선택)**: 사용자가 텍스트를 입력하면 해당 내용을 “화풍/렌더링 힌트”로 사용(비우면 기본 동작)
- **출력**: 표정 포트레이트 9개가 **3×3 그리드 1장**으로 생성되어 갤러리에 저장됨
- **일관성**:
  - 동일 캐릭터 정체성(얼굴/헤어/인상) 유지
  - 스타일/조명/배경은 최대한 균일(워크플로우 style_prompt 의도대로)
- **UX**:
  - UI에서 “표정 시트 옵션(9/4)” 선택이 실제 프롬프트 구성에 반영됨
  - 진행률/대기열/취소가 정상 동작(WS+jobs polling)

---

### 작업 범위(이번 세션/다음 세션에서 할 일)
- **1) 설정 확인**
  - `app/workflow_configs.py`에서 `NanoBanana_ExpressionPortraitSheet`의 UI 스키마/프롬프트가 의도와 일치하는지 점검
  - 프론트에서 9/4 선택값이 request payload(또는 user_prompt 확장)로 들어가는지 확인
  - “스타일(선택)” 입력이 비어있을 때 default_user_prompt로 안정적으로 fallback 되는지 확인

- **2) 프론트 → 백엔드 payload 경로 확인**
  - `templates/index.html`에서:
    - 입력 이미지 선택 시 `input_image_id` / `input_image_ids`가 어떻게 세팅되는지 확인
    - expression tool 옵션(9/4)이 어떤 방식으로 `user_prompt`에 합쳐지는지 확인
    - “스타일(선택)” 텍스트가 default_user_prompt에 어떤 포맷으로 합쳐지는지 확인(스타일만 반영되게)

- **3) 백엔드 프롬프트 구성 검증**
  - `app/services/generation.py` + `app/services/google_nano_banana.py`에서:
    - 최종 prompt가 “9개 시트(3×3), 텍스트 없음, 동일 정체성 유지” 조건을 충분히 강제하는지 점검
  - 필요 시: 워크플로우의 `style_prompt` 또는 프론트에서 붙이는 extra prompt 문구를 보강(최소 변경)

- **4) 테스트(수동)**
  - 입력 이미지 1장 업로드 → 워크플로우 선택 → 9개 생성
  - 결과가 3×3 “한 장”으로 저장되는지 확인
  - 취소/재시도/에러 메시지(쿼터/키/네트워크) 확인

---

### 리스크/주의사항
- **Google 모델의 자유도** 때문에, “정확히 9개 패널 + 그리드 + 텍스트 없음”을 항상 만족하지 않을 수 있음  
  → style_prompt/추가 지시문(Format) 강화가 필요할 수 있음
- **입력 비율**은 tool 정책상 square 고정이 안정적(현재 UI도 square만 노출)
- **쿼터/레이트리밋**: NanoBanana 호출 실패 시 사용자 메시지가 “재시도/운영자 문의”로 명확해야 함

---

### 관련 파일(빠른 링크)
- 워크플로우 정의: `app/workflow_configs.py`
- 생성 처리: `app/services/generation.py`
- Google 호출/에러 분류: `app/services/google_nano_banana.py`
- 프론트 생성 로직: `templates/index.html`
- 입력 업로드/보관함: `app/routers/inputs.py`, `app/services/media_store.py`

