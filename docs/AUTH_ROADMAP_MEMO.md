# 인증/사용자 관리 로드맵 메모 (점진적 도입)

## 목표
- 간단한 세션/게스트 단계에서 시작해도, 추후 OAuth/이메일 로그인, RBAC로 자연스럽게 확장
- 이미지 스토리지 스킴과 일관된 `user_id`(UUID/ULID)로 리소스 소유권을 명확히

## 1) 초기 단계(게스트 + 최소 세션)
- 게스트 네임스페이스: outputs/users/guest/{session_id}/...
- 세션 보관: 서버 메모리/서명 쿠키(만료 짧게), CSRF 방어
- 제한: 게스트 쿼터(갯수/용량/보존기간), 이후 로그인 유도

### (현 구현 상태)
- 게스트 식별: 브라우저 쿠키 `anon_id` 사용
- 실시간 일치: HTTP와 WebSocket 모두 동일 `anon_id`로 사용자 식별 일치 (WS `?anon_id=...`)
- 작업 스코프: JobManager가 `owner_id = anon_id` 기준으로 큐잉/진행/취소/브로드캐스트 관리

## 2) 기본 로그인(이메일/비밀번호 또는 Magic Link)
- Password: 해시(Argon2/Bcrypt), 비밀번호 재설정 토큰(만료), 이메일 검증
- Magic Link(선호): 이메일 링크 기반 1회성 토큰 로그인
- 토큰: 세션 쿠키(HTTPOnly, Secure), 짧은 수명 + 갱신
- 사용자 프로필: { id(ULID), email, email_verified, created_at, plan, quota }

### (마이그레이션 가이드: anon_id → user_id)
- 전환 시점부터 서버는 `request.user.id`를 `owner_id`로 사용
- 기존 코드의 `anon_id` 참조 지점은 "사용자 식별자" 추상으로 설계되어 값 교체만으로 동작
  - 템플릿 data 속성: `data-anon-id` → 인증 시 `data-user-id`(또는 동일 키에 값만 교체)
  - WebSocket: `?anon_id=` 대신 인증된 `user_id` 주입
  - JobManager/RR 스케줄러 변경 없음 (키 문자열만 교체)
- 게스트 보관물 이관: 게스트 출력물의 `owner=anon-*`을 신규 `user_id`로 재태깅(폴더/메타 갱신)

## 3) 소셜 로그인(OAuth 2.0 / OIDC)
- Google/GitHub/Apple 등 프로바이더 연결, 이메일/프로필 동기화
- 내부 `user_id`는 별도 유지, 외부 계정은 연결 테이블로 관리

## 4) 권한/역할(RBAC)
- roles: [user, pro, admin]
- 정책: 자신의 리소스만 CRUD, admin은 관리 도구 접근
- 리소스 접근은 항상 서버가 `user_id` 스코프로 필터

## 5) 보안 원칙
- 모든 민감 토큰/쿠키는 HTTPOnly/SameSite/Strict, Secure
- 프리사인 URL로 파일 접근(짧은 만료, 1회성 가능)
- Rate limit/속도 제한, 로그인 시도 제한, 2FA(추가 단계)

## 6) API/프론트 연동
- 클라이언트: 로그인 상태 감지 → `/me`로 프로필/쿼터 가져오기
- 서버: 미들웨어로 인증 검사, `request.user.id`를 통해 스코프 강제
- 이미지 API는 항상 `user_id` 스코프 기준으로 목록/조회/삭제

### (Job/Event 연동 기준)
- 생성 API 응답: `{ job_id, status:'queued', position }`
- 상태/취소: `/api/v1/jobs/{job_id}`, `/api/v1/jobs/{job_id}/cancel`
- 실시간: 사용자 스코프 WS 채널에 `job_id` 포함 이벤트(`queued|running|complete|cancelled|error`)
- 로깅: 구조화 로그(JSON)로 잡 상태 변경/거절(429)/WS 연결 기록 → 운영 가시성 강화

## 7) 마이그레이션/운영
- 게스트 → 회원 전환: 게스트 세션의 이미지 소유권을 신규 `user_id`로 이관
- 감사 로그: 로그인/삭제/복구 이벤트 로깅
- 백업/복구: 사용자 단위 내보내기/불러오기

## 8) 향후(구독/결제)
- Stripe 등 결제 연동, 플랜별 쿼터/보존기간/해상도 제한
- 청구 이벤트에 따른 역할/권한 자동 변경

(인증 도입 시 이 메모를 최신 상태로 유지합니다)
