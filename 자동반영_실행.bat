@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Blue365 QMS - 자동 반영(지정 엑셀 1회 반영)
rem 매일 지정한 엑셀 1개를 읽어 품질 DB에 반영한다(작업 스케줄러가 호출). 파일은 옮기지 않는다.

set "SYNCFILE=%~1"
if "%SYNCFILE%"=="" set "SYNCFILE=%~dp0data\Blue365_QMS.xlsx"

rem ── 파이썬 찾기: QMS_PY → 설치본 → py → python ──
set "PY="
if defined QMS_PY if exist "%QMS_PY%" set "PY=%QMS_PY%"
if not defined PY if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "C:\Blue365_QMS\py\python.exe" set "PY=C:\Blue365_QMS\py\python.exe"
if not defined PY ( py -3 -c "import sys" >nul 2>nul && set "PY=py -3" )
if not defined PY ( python -c "import sys" >nul 2>nul && set "PY=python" )
if not defined PY goto nopy

if not exist "%SYNCFILE%" goto nofile
if not exist "%~dp0logs" mkdir "%~dp0logs"

echo [%date% %time%] 반영 시작: "%SYNCFILE%" >> "%~dp0logs\auto_sync.log"
%PY% "%~dp0qms_monitor.py" --sync-file "%SYNCFILE%" >> "%~dp0logs\auto_sync.log" 2>&1
set "RC=%ERRORLEVEL%"
echo [%date% %time%] 종료 코드 %RC% >> "%~dp0logs\auto_sync.log"
echo. >> "%~dp0logs\auto_sync.log"
exit /b %RC%

:nopy
echo [%date% %time%] [오류] 파이썬을 찾지 못했습니다. QMS_PY 환경변수를 설정하세요. >> "%~dp0logs\auto_sync.log"
exit /b 1
:nofile
if not exist "%~dp0logs" mkdir "%~dp0logs"
echo [%date% %time%] [오류] 파일 없음: "%SYNCFILE%" >> "%~dp0logs\auto_sync.log"
exit /b 1
