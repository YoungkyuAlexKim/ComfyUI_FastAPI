#!/usr/bin/env python3
"""
ComfyUI FastAPI 서버 실행 스크립트
"""

import uvicorn
import os
import sys

def main():
    """FastAPI 서버를 실행합니다."""

    # 현재 디렉토리를 프로젝트 루트로 설정
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)

    # Python 경로에 app 디렉토리 추가
    sys.path.insert(0, project_root)

    print("🚀 ComfyUI FastAPI 서버를 시작합니다...")
    print("📍 서버 주소: http://127.0.0.1:8000")
    print("📍 API 문서: http://127.0.0.1:8000/docs")
    print("🛑 종료하려면 Ctrl+C를 누르세요")
    print("-" * 50)

    # Uvicorn으로 FastAPI 앱 실행
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,  # 코드 변경 시 자동 재시작
        log_level="info"
    )

if __name__ == "__main__":
    main()
