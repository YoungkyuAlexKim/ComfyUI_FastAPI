# 내부 MCP 서버

> 최종 업데이트: 2026-08-18
>
> 서버 이름: `LC AI Canvas`
>
> 구현 버전: `0.8.0`
>
> 전송: Streamable HTTP `/mcp/`

LC AI Canvas MCP는 사내 데스크톱·IDE 에이전트가 회사의 이미지 생성·저장·비용 감사
파이프라인을 대화로 사용할 수 있게 합니다. Codex 앱·IDE와 Claude Code는 실제 사내
클라이언트로 검증했습니다.

일반 ChatGPT Chat 모드, Claude Desktop 일반 채팅과 Claude.ai 웹의 원격 커스텀 connector는
현재 지원 범위가 아닙니다. Claude Desktop 지원은 인프라가 DNS·HTTPS 프록시 기반 원격 MCP
접속 정책을 확정할 때 다시 검토합니다.

## 공개 도구

| 도구 | 역할 | 비용·변경 경계 |
|---|---|---|
| `list_generation_capabilities` | 공개 capability 목록 | 읽기 전용 |
| `get_generation_capability` | 입력·출력·선택지 계약 | 읽기 전용 |
| `plan_generation` | 옵션 계획·모호성 판정·단기 plan ID | provider 호출 없음 |
| `list_image_assets` | 소유한 active image/input 목록 | 읽기 전용 |
| `get_image_asset` | 소유 자산 메타데이터·이미지 content | 읽기 전용 |
| `prepare_input_image_upload` | 직접 multipart 업로드 주소·제약 조회 | 읽기 전용, provider 호출 없음 |
| `create_managed_image_asset` | 기본 생성 또는 소유 자산 참고 편집 | 외부 API 비용 가능 |
| `create_game_ui_assets` | 고정 2×2 Game UI 그룹 | 외부 API 비용 가능 |
| `create_character_sheet` | 턴어라운드·표정 시트 | 외부 API 비용 가능 |
| `create_storyboard` | 6·9컷 스토리보드 | 외부 API 비용 가능 |
| `remove_background` | 고정 RMBG-2.0 배경 제거 | 로컬 GPU, 외부 provider 비용 없음 |
| `get_generation_job` | 소유 작업 상태 조회 | 읽기 전용 |
| `get_generation_result` | 완료 결과·미리보기·원본 링크 | 읽기 전용 |

## 계획과 사용자 확인

모든 공개 생성 쓰기는 먼저 `plan_generation`을 통과합니다. 계획 단계는 provider나 로컬
workflow를 실행하지 않으므로 이미지 생성 비용이 들지 않습니다.

- `selection_mode=clarify`: 사용자가 밝히지 않은 결정과 선택지를 반환합니다.
  `missing_decisions`가 남으면 plan ID를 발급하지 않습니다.
- `selection_mode=recommend`: 사용자가 “알아서 추천해줘”처럼 선택을 명시적으로 위임한
  경우에만 사용합니다.
- 준비된 계획: 호출자, 프롬프트, 참고 자산과 전체 옵션에 묶인 30분짜리 `plan_id`, 정확한
  `tool_arguments`, `suggested_idempotency_key`를 반환합니다.
- 쓰기 제출: plan 누락·만료·소유자 변경·인자 변경을 큐 등록 전에 거절합니다.

LLM은 `missing_decisions`를 한 번의 짧은 질문으로 묶습니다. 사용자가 모델·크기·품질과
실행 의사를 이미 정했으면 같은 내용을 반복해서 묻지 않습니다. 같은 의도의 네트워크
재시도에는 새 멱등성 키를 만들지 않습니다.

사전 비용은 운영 가격표가 정확히 일치할 때만 숫자입니다. 가격표가 없으면
`estimated_cost_usd=null`, `cost_estimate_available=false`이며 무료라는 뜻이 아닙니다.
완료 뒤 provider actual cost는 관리자 화면에서 IP·기능·모델별로 집계됩니다. ComfyUI
workflow의 `0.0`은 외부 provider API 비용만 뜻합니다.

## capability 계약

### 일반 이미지

`create_managed_image_asset`은 `reference_image_ids`가 없으면 텍스트→이미지, 소유한 active
image/input ID가 있으면 이미지 편집입니다.

- 모델: Nano Banana Pro, Nano Banana 2, Nano Banana 2 Lite, GPT Image 2
- 비율: `square`, `landscape`, `portrait`; 편집은 `auto` 추가
- 크기: 모델별 `1K`, `2K`; Lite는 `1K` 전용
- 품질: GPT Image 2의 `low`, `medium`, `high`
- 참고 이미지: 최대 14장, provider 실행 한도는 더 작을 수 있음

첨부 파일은 `/api/v1/mcp/inputs/upload`로 multipart 직접 전송합니다. PNG/JPEG/WEBP만
허용하며 byte·pixel 제한, 실제 형식 검사, EXIF 방향과 PNG 정규화를 적용합니다. 같은
owner·정규화 SHA-256 재시도는 기존 active input을 반환합니다. Base64 문자열과 이미지
바이트를 MCP 도구 인자에 넣는 경로는 공개하지 않습니다.

Codex·Claude Code는 `prepare_input_image_upload`로 주소와 제한을 받은 뒤 로컬 HTTP/file
도구로 `file` 필드를 전송합니다. 업로드 응답의 `asset_id`만 이후
`reference_image_ids`에 넣습니다.

### Game UI

웹은 2×2·3×3·4×4를 지원하지만 MCP는 검증된 `2x2`, 4개, 2K 계약만 공개합니다. 참고
이미지는 최대 3장이고 결과는 child 이미지 4개, 그룹 metadata와 ZIP입니다. 가변 grid와
그룹 삭제 도구는 공개하지 않습니다.

### 캐릭터 시트와 스토리보드

두 도구 모두 호출자 소유 active 참고 이미지 한 장이 필요하고 현재 서버 선택
GPT Image 2를 사용합니다.

- 턴어라운드: 3·5·8뷰
- 표정 시트: 4·9개
- 스토리보드: 6컷 2×3 또는 9컷 3×3
- 크기·품질: `1K|2K`, `low|medium|high`

1K/low는 저비용 계약 확인용 초안입니다. 사용자가 선택을 위임할 때만 2K/medium을
권장합니다. 실제 3뷰·표정 4개·6컷 표본은 exact count와 MCP image content를 통과했습니다.
스토리보드 표본의 자동 gutter 제거는 fallback되어 얇은 패널 구분선이 남은 적이 있으므로
품질 관찰 항목으로 유지합니다.

### 배경 제거

`remove_background`는 호출자 소유 active image/input 한 장을 고정 `RMBG2` workflow와
`RMBG-2.0` 모델로 처리합니다. `mask_blur`는 0~64, `mask_offset`은 -64~64이고 기본값은
모두 0입니다. 원본을 덮어쓰지 않고 투명 PNG를 새 자산으로 저장합니다.

“배경 지워줘”, “누끼 따줘”는 이 도구를 바로 선택할 수 있습니다. “배경 정리해줘”는
제거·교체·흐림 중 의미를 묻습니다. 배경 교체·흐림은 현재 범용 managed 편집으로 처리하면
외부 API 비용이 발생합니다. See-Through와 ACE-Step은 장시간 로컬 workflow라 MCP에
노출하지 않습니다.

## 표준 호출 흐름

1. `list_generation_capabilities` 또는 `get_generation_capability`
2. `prepare_input_image_upload` 확인 뒤 로컬 파일을 multipart로 직접 업로드
3. 기존 참고 이미지는 `list_image_assets`와 `get_image_asset`으로 확인
4. 명시된 선택만 넣어 `plan_generation(selection_mode=clarify)` 호출
5. `missing_decisions`가 있으면 사용자에게 한 번에 질문하고 다시 계획
6. 사용자가 선택을 위임했을 때만 `selection_mode=recommend` 사용
7. 준비된 `tool_arguments`, `plan_id`, `suggested_idempotency_key`로 쓰기 호출
8. `cost_confirmation_required`가 반환되면 사용자 확인 뒤 같은 계획·키에 `cost_confirmed=true`로 재호출
9. `get_generation_job`을 완료 또는 오류까지 polling
10. `get_generation_result` 호출
11. 사용자에게 실제 미리보기 또는 표시 불가 안내와 원본 링크 제공

## 결과 표시 계약

MCP 도구 결과에 이미지가 포함됐다는 사실과 최종 사용자 채팅에 썸네일이 보였다는 사실은
같지 않습니다. 클라이언트가 tool result를 접거나 `ImageContent`를 최종 답변에 승격하지
않을 수 있기 때문입니다.

0.8.0의 `get_generation_result`는 다음 fallback을 함께 제공합니다.

- 최대 768px WebP user-preview를 첫 `ImageContent`로 반환
- `annotations.audience=[user]`, 높은 표시 우선순위
- `presentation.required=true`
- 권장 방식 `download_then_native_image_viewer`
- 작업 ID 기반 세션용 임시 PNG 파일명
- 재생성 금지와 원본 LC AI Canvas 링크 유지

로컬 다운로드·이미지 보기 도구가 있는 Codex·Claude Code에는 원본을 임시 PNG로
내려받아 실제로 연 뒤 완료 답변을 하도록 요구합니다. 로컬 도구가 없으면 반환된
user-preview 또는 호환 UI를 사용합니다. 어느 방식도 보장할 수 없으면 미리보기 불가
가능성을 밝히고 원본 링크를 제공합니다.

Codex에서 로컬 파일 다운로드와 이미지 보기로 썸네일을 표시한 표본은 통과했습니다.
다른 새 세션이 이 후처리를 한 차례 생략한 사례를 반영해 계약을 강화했지만, 서버가 원격
클라이언트의 최종 렌더링을 강제할 수는 없습니다. Claude Code의 생성·연속 편집과 서버
결과 저장은 실기기에서 통과했습니다. HTTPS나 소유권 검사를 약화하지 않고 직접 링크
fallback을 유지합니다.

## 네트워크와 신원

MCP는 서버가 해석한 클라이언트 IP의 해시를 principal로 사용합니다. 요청 본문의 IP나
principal은 신뢰하지 않습니다.

- `TRUSTED_PROXY_CIDRS`: `X-Forwarded-For`를 신뢰할 수 있는 바로 앞 프록시
- `MCP_ALLOWED_CLIENT_CIDRS`: 선택적 애플리케이션 2차 허용 목록
- `MCP_WEB_LINK_ENABLED`: 같은 IP의 웹↔MCP 갤러리 명시적 연결
- `MCP_PUBLIC_BASE_URL`: 온보딩과 결과 링크의 canonical origin

인프라팀은 사용자 PC별 원본 IP 고유성, DHCP 예약·재할당 이력, 프록시·VPN의 원본 IP
보존과 8000 포트의 사내망 제한을 책임집니다. 이 전제가 유지되는 동안 별도 OAuth는
현재 1차 범위에 포함하지 않습니다.

### canonical 주소

사내 사용자는 웹, `/mcp-connect`와 MCP에 같은 공식 주소를 사용해야 합니다. 서버 PC에서
웹을 `localhost`로 열고 MCP는 사내 IP로 등록하면 서버가 각각 `127.0.0.1`과 LAN IP로
관찰하므로 별도 MCP owner가 됩니다. 브라우저 쿠키도 host별이라 웹 principal이 나뉩니다.

실제 검증에서 두 owner의 자산이 분리된 것을 확인했고, 웹을 사내 IP로 다시 열어 연결한
뒤 해당 IP의 과거·신규 MCP 이미지가 함께 나타났습니다. 데이터 손실이나 복제가 아니라
서로 다른 owner에 대한 조회 차이였습니다. `localhost`는 개발 전용으로만 사용하고 운영
온보딩에는 공식 origin만 배포합니다.

### 웹 갤러리 연결

`MCP_WEB_LINK_ENABLED=true`이면 현재 웹 요청 IP에 대응하는 MCP workspace를 한 번
`연결하기`로 연결할 수 있습니다.

- 연결은 SQLite에 유지되고 서버·브라우저 재시작으로 풀리지 않습니다.
- 원본 owner와 감사 기록은 바뀌지 않습니다.
- MCP 이미지는 웹 갤러리에서 `MCP`로 표시됩니다.
- 연결된 웹 principal은 MCP 이미지를 일반 이미지와 함께 선택해 휴지통으로 이동하고 복구할
  수 있습니다. Game UI child는 전체 묶음 상태 변경으로 승격합니다.
- 쇼케이스 공유는 계속 막고 편집 시 웹 input 복사본을 만듭니다.
- 연결 해제는 목록 관계만 제거하며 원본을 삭제하지 않습니다.
- 이미 다른 웹 principal에 연결된 workspace는 409로 takeover를 차단합니다.
- MCP 자산 목록에 웹 자산을 역으로 합치지 않습니다.

API는 `GET|POST|DELETE /api/v1/principal-links/mcp`입니다. MCP media URL은 같은 IP 또는
명시적으로 연결된 웹 principal만 열 수 있고 다른 요청과 JSON sidecar에는 404를 반환합니다.

### IP 재할당 위험

현재 `IP → MCP owner`는 결정적이므로 퇴사·PC 교체 뒤 같은 IP를 다른 사람에게 재할당하면
이전 workspace가 다시 선택될 수 있습니다. 이때 과거 자산과 비용 기록이 새 사용자에게
이어질 위험이 있습니다.

인프라팀의 실제 재할당 정책을 먼저 확인합니다. 필요하면 기존 workspace를 retired 처리하고
비용·감사 기록은 보존한 채 같은 IP에 새 allocation generation과 새 owner를 발급하는 운영
기능을 추가합니다. 이 기능은 아직 구현되지 않았습니다. DB 행과 파일을 수동으로 일부만
삭제하는 것은 안전한 초기화 절차가 아닙니다.

## 사내 온보딩

`/mcp-connect`는 사내 게시판에 공유할 데스크톱·IDE용 안내 페이지입니다. Codex 앱·VS Code와
Claude Code 탭, 실제 MCP 주소, 비용 없는 최초 확인 문장과 갤러리 연결 안내를 제공합니다.
`MCP_PUBLIC_BASE_URL`이 있으면 이를 사용하고 없으면 현재 요청 origin을 사용합니다.

일반 웹 화면에는 공용 비밀번호가 없습니다. 외부 접근은 사내망·방화벽이 차단하고 관리자
인증, 웹 서명 쿠키와 MCP IP 경계는 유지합니다. 최초 확인 문장은 생성 도구를 호출하지 않아
외부 이미지 API 비용이 들지 않습니다.

## Claude Code 설정

회사 네트워크의 워크스테이션에서 실행합니다.

```powershell
$McpUrl = "http://SERVER_IP:8000/mcp/"
claude mcp add --transport http --scope user lc_ai_canvas $McpUrl
claude mcp get lc_ai_canvas
```

user scope는 같은 컴퓨터의 다른 프로젝트에서도 유지됩니다. 프로젝트에만 한정하려면 local
scope를 사용합니다. 형식은 [Claude Code MCP 문서](https://code.claude.com/docs/en/mcp)를
기준으로 합니다. 사내 동료 계정에서 기능 조회, 직접 입력 업로드, GPT Image 2 1K 편집
2회를 확인했습니다.

## Codex 설정

사용자 또는 신뢰한 프로젝트의 `config.toml`에 등록합니다.

```toml
[mcp_servers.lc_ai_canvas]
url = "http://SERVER_IP:8000/mcp/"
default_tools_approval_mode = "writes"
```

사용자 설정은 `~/.codex/config.toml`, 프로젝트 설정은 `.codex/config.toml`을 사용합니다.
VS Code에서는 설정 뒤 `Developer: Reload Window`를 실행하고 기존 대화에 도구가 없으면 새
대화를 시작합니다.

```powershell
codex mcp get lc_ai_canvas
codex mcp list
```

현재 사내 IP 운영에서는 bearer token이나 OAuth를 사용하지 않습니다. 형식은
[Codex MCP 문서](https://developers.openai.com/codex/mcp/)를 기준으로 합니다.

## 운영·선택 항목

1. 인프라팀의 IP 재할당 정책 확인과 필요 시 owner generation 기능
2. actual cost 표본 기반 모델·크기·품질별 사전 비용표
3. 장시간·다사용자 RMBG 큐 표본
4. 스토리보드 gutter fallback 품질 보강
5. 필요성이 확인된 작업 취소·휴지통 또는 MCP Apps UI

영구 삭제와 관리자 정책 변경은 MCP에 공개하지 않습니다.
