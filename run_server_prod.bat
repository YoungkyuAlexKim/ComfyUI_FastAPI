@echo off
setlocal

echo [INFO] ComfyUI FastAPI 서버(운영 모드)를 시작합니다...
echo [INFO] - reload 비활성화(안정성)
echo [INFO] - 외부 접속 허용(host 0.0.0.0)
echo.

REM 가상환경 활성화
if exist venv\Scripts\activate.bat (
  call venv\Scripts\activate.bat
) else (
  echo [ERROR] venv\Scripts\activate.bat 를 찾지 못했습니다. 먼저 venv 구성을 확인해주세요.
  exit /b 1
)

REM 운영 모드 실행 (필요시 포트 변경: --port 8000)
uvicorn app.main:app --host 0.0.0.0 --port 8000

REM 서버 종료 후 가상환경 비활성화
deactivate
endlocal


