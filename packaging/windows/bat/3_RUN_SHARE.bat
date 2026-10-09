@echo off
setlocal
cd /d "%~dp0"
title Blue365 QMS - 사내망 공유 실행 중 - 이 창을 닫으면 프로그램이 종료됩니다
if not exist "%~dp0py\python.exe" goto nopy
"%~dp0py\python.exe" -E -s "%~dp0tools\qms_launcher.py" run --share %*
if errorlevel 1 pause
exit /b
:nopy
echo.
echo [오류] py\python.exe 파일이 없습니다.
echo   1. ZIP 파일 안에서 바로 실행하지 말고, 먼저 압축을 모두 푼 뒤 실행하세요.
echo   2. 압축은 C:\ 에 풀어 C:\Blue365_QMS 가 되도록 하는 것을 권장합니다.
echo   3. 보안 프로그램이 파일을 지웠다면 IT 담당자에게 예외 등록을 요청하세요.
echo.
pause
exit /b 1
