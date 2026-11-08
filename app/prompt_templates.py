from typing import Dict, List, TypedDict


class PromptTemplate(TypedDict, total=False):
    title: str  # 버튼에 표시할 제목
    text: str   # 프롬프트 필드에 추가될 실제 태그/문구
    # 옵션형 템플릿: text 내 '[ITEM]' 자리에 무작위 옵션을 치환합니다.
    # 만약 텍스트에 [ITEM]이 없으면, 선택된 옵션을 뒤에 붙입니다.
    options: List[str]


# 워크플로우별 추천 프롬프트 템플릿 정의
# 필요 시 언제든 이 파일만 수정하여 관리할 수 있습니다.
PROMPT_TEMPLATES: Dict[str, List[PromptTemplate]] = {}
