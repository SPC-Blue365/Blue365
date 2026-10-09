@echo off
setlocal
cd /d "%~dp0"
title Blue365 QMS - 방화벽 허용 (관리자 권한 필요)
if not exist "%~dp0py\python.exe" goto nopy
echo 사내망의 다른 PC가 이 PC의 Blue365 QMS에 접속할 수 있도록 Windows 방화벽 허용 규칙을 등록합니다.
echo 이 파일은 마우스 오른쪽 버튼 - '관리자 권한으로 실행' 으로 실행해야 합니다.
echo.
"%~dp0py\python.exe" -E -s "%~dp0tools\qms_launcher.py" firewall add %*
echo.
pause
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
