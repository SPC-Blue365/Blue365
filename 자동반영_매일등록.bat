@echo off
setlocal
cd /d "%~dp0"
title Blue365 QMS - 자동 반영 등록(매일 오전 6시)
set "TASKNAME=Blue365_QMS_자동반영"
set "JOB=%~dp0자동반영_실행.bat"
set "SYNCFILE=%~dp0data\Blue365_QMS.xlsx"

echo.
echo  [Blue365 QMS 자동 반영]
echo   매일 오전 6시에 아래 엑셀을 읽어 품질 시스템에 자동 반영합니다.
echo     %SYNCFILE%
echo   (이 파일을 매일 같은 자리에 덮어써 두면 됩니다. 파일 이름은 Blue365_QMS.xlsx 로 맞추세요.)
echo   반영 후 조회 전용 현황판도 만듭니다: %~dp0현황판\Blue365_현황_최신.html
echo     (BAT 실행이 안 되는 PC에서도 이 HTML 파일을 더블클릭하면 브라우저로 볼 수 있습니다.)
echo   ※ 반영은 이 PC가 켜져 있고 로그인되어 있을 때 실행됩니다.
echo.
echo   1. 자동 반영 등록 - 매일 오전 06:00
echo   2. 자동 반영 해제
echo   3. 지금 1회 반영 - 결과를 이 창에 표시
echo   4. 등록 상태 보기
echo   5. 닫기
echo.
choice /c 12345 /n /m "번호를 선택하세요 [1-5]: "
set SEL=%ERRORLEVEL%
if "%SEL%"=="1" goto reg
if "%SEL%"=="2" goto unreg
if "%SEL%"=="3" goto runnow
if "%SEL%"=="4" goto status
exit /b 0

:reg
schtasks /create /tn "%TASKNAME%" /tr "cmd /c \"\"%JOB%\"\"" /sc DAILY /st 06:00 /f
if errorlevel 1 goto regfail
echo.
echo [완료] 매일 오전 6시 자동 반영을 등록했습니다.
echo   해제하려면 이 파일을 다시 실행해 2번을 선택하세요.
echo   실행 기록: %~dp0logs\auto_sync.log
goto end

:regfail
echo.
echo [오류] 등록에 실패했습니다. 이 PC에서 작업 스케줄러 사용 권한을 확인하거나,
echo        이 창을 '관리자 권한으로 실행' 후 다시 시도하세요.
goto end

:unreg
schtasks /delete /tn "%TASKNAME%" /f
echo.
echo [완료] 자동 반영 등록을 해제했습니다.
goto end

:runnow
echo.
echo 지금 1회 반영합니다...
call "%JOB%"
echo.
echo [완료] 결과는 %~dp0logs\auto_sync.log 에 기록했습니다. 아래는 최근 기록입니다.
echo --------------------------------------------------
if exist "%~dp0logs\auto_sync.log" powershell -NoProfile -Command "Get-Content -Tail 20 -Encoding UTF8 '%~dp0logs\auto_sync.log'"
goto end

:status
echo.
schtasks /query /tn "%TASKNAME%" /v /fo LIST 2>nul | findstr /i "TaskName 다음 Next 상태 Status 마지막 Last"
if errorlevel 1 echo (등록된 자동 반영 작업이 없습니다. 1번으로 등록하세요.)
goto end

:end
echo.
pause
exit /b
