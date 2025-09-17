@echo off
echo 🚀 ComfyUI FastAPI 서버를 시작합니다...

REM 가상환경 활성화
call venv\Scripts\activate.bat

REM 서버 시작을 백그라운드에서 실행하고 브라우저 열기
start /B cmd /c "timeout /t 3 /nobreak > nul && start http://127.0.0.1:8000"

REM FastAPI 서버 실행 (--reload 옵션으로 코드 변경 시 자동 재시작)
echo ⏳ 서버를 시작합니다...
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

REM 가상환경 비활성화 (서버 종료 시)
deactivate
