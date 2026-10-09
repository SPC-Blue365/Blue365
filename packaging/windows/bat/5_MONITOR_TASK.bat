@echo off
setlocal
cd /d "%~dp0"
title Blue365 QMS - 자동 감시 (작업 스케줄러)
if not exist "%~dp0py\python.exe" goto nopy
echo.
echo  [Blue365 QMS 자동 감시]
echo   LIMS 결과 동기화, 이상 감지, 알림 발송을 정해진 간격으로 자동 실행합니다.
echo   프로그램 화면을 열어 두지 않아도 동작합니다. 단, 이 PC에 로그인해 있어야 합니다.
echo.
echo   1. 자동 감시 등록 - 30분마다
echo   2. 자동 감시 해제
echo   3. 지금 1회 실행 - 결과를 이 창에 표시
echo   4. 등록 상태와 최근 실행 기록 보기
echo   5. 닫기
echo.
choice /c 12345 /n /m "번호를 선택하세요 [1-5]: "
set SEL=%ERRORLEVEL%
set ACT=
if "%SEL%"=="1" set ACT=register
if "%SEL%"=="2" set ACT=unregister
if "%SEL%"=="3" set ACT=run-now
if "%SEL%"=="4" set ACT=status
if not defined ACT exit /b 0
echo.
"%~dp0py\python.exe" -E -s "%~dp0tools\qms_launcher.py" task %ACT%
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
