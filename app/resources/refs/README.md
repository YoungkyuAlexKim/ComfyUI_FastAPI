# 서버 전용 숨김 레퍼런스

브라우저 정적 파일로 노출하지 않고 서버가 특화 workflow 실행 시 자동 첨부하는 내부
레퍼런스 이미지를 보관합니다.

## 체인소주스킹 캐릭터 생성

- workflow ID: `NanoBanana_ChainsawJuiceKingCharacter`
- capability: `internal_image_preset/chainsaw_juice_king`
- provider/model: OpenRouter / GPT Image 2
- 파일: `chainsaw_juice_king_reference.png`
- 위치: `app/resources/refs/chainsaw_juice_king_reference.png`
- MCP 공개: 아니요

`NanoBanana`는 기존 결과 및 웹 요청 호환을 위한 workflow 이름입니다. 이 기능은 Google
API를 직접 호출하지 않습니다. 레퍼런스 파일이 없으면 실행을 중단하고 사용자에게
설정 오류를 반환합니다.

새 숨김 레퍼런스를 추가할 때는 공개 정적 mount 아래에 두지 말고, workflow 설정과
preflight 오류, 라이선스 및 사내 사용 범위를 함께 문서화합니다.
