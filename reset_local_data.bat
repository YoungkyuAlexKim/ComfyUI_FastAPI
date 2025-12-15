@echo off
setlocal

echo [WARN] 로컬 데이터(갤러리/입력/컨트롤/DB)를 초기화합니다.
echo [WARN] - db\app_data.db (및 -wal/-shm)
echo [WARN] - outputs\users\ 전체
echo.
set /p OK=정말 삭제할까요? (YES 입력 시 진행): 
if /I not "%OK%"=="YES" (
  echo [INFO] 취소되었습니다.
  exit /b 0
)

REM DB 제거
if exist db\app_data.db del /f /q db\app_data.db
if exist db\app_data.db-wal del /f /q db\app_data.db-wal
if exist db\app_data.db-shm del /f /q db\app_data.db-shm

REM outputs\users 제거 후 재생성
if exist outputs\users rmdir /s /q outputs\users
mkdir outputs\users >nul 2>&1

echo [OK] 초기화 완료.
endlocal


