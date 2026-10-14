@echo off
setlocal
cd /d "%~dp0"
title Blue365 QMS - 코드로 실행 (이 창을 닫으면 종료)
echo [Blue365 QMS - 코드로 실행]
echo   코드 폴더: %CD%
echo.

rem ── 1. 코드 폴더 확인(main 브랜치의 채팅 예제가 아닌 QMS 코드인지) ──
if not exist "streamlit_app.py" goto nocode
if not exist "qms\shipment.py" goto nocode
if not exist "app_pages\" goto nocode

rem ── 2. 파이썬 찾기: QMS_PY(직접 지정) → 설치 패키지 python → py 런처 → python ──
set "PY="
if defined QMS_PY if exist "%QMS_PY%" set PY="%QMS_PY%"
if not defined PY if exist "..\Blue365_QMS\py\python.exe" set PY="..\Blue365_QMS\py\python.exe"
if not defined PY if exist "C:\Blue365_QMS\py\python.exe" set PY="C:\Blue365_QMS\py\python.exe"
if not defined PY (
  py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY goto nopy
echo   파이썬: %PY%
%PY% -c "import sys; print('   버전:', sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto oldpy

rem ── 3. 구성요소 확인 → 없으면 설치(인터넷 또는 사내 pip 저장소 필요) ──
%PY% -c "import streamlit, pandas, numpy, scipy, plotly, openpyxl, pptx; v = tuple(int(x) for x in streamlit.__version__.split('.')[:2]); raise SystemExit(0 if v >= (1, 55) else 1)" >nul 2>nul
if not errorlevel 1 goto run
echo.
echo   구성요소가 없거나 오래되어 설치합니다(처음 1회, 수 분 소요)...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto nopip

:run
echo.
echo   시작합니다. 브라우저가 열리지 않으면 http://localhost:8501 을 직접 여세요. (종료: 이 창 닫기 또는 Ctrl+C)
echo.
rem 기본은 내 PC 전용(127.0.0.1). 사내망 공유: RUN_CODE.bat --server.address 0.0.0.0
%PY% -m streamlit run streamlit_app.py --server.address 127.0.0.1 --browser.gatherUsageStats false %*
if errorlevel 1 goto failrun
exit /b 0

:nocode
echo [오류] 이 폴더에 QMS 코드가 없습니다(streamlit_app.py, qms, app_pages 폴더 필요).
echo   - GitHub 첫 화면(main 브랜치)에서 받으면 'Chatbot' 예제만 들어 있습니다.
echo   - 브랜치를 ccr-4c0c953d-ll1jyd 로 바꾼 뒤 Code - Download ZIP 으로 받거나,
echo     담당자가 보낸 코드 ZIP을 풀고, 그 안의 이 파일(RUN_CODE.bat)을 실행하세요.
goto end

:nopy
echo [오류] 파이썬을 찾지 못했습니다.
echo   방법 1(권장, 인터넷 불필요): 이미 설치한 QMS 패키지의 파이썬을 씁니다.
echo     이 코드 폴더를 Blue365_QMS 폴더 옆에 두거나, 아래처럼 위치를 지정한 뒤 다시 실행하세요.
echo       set QMS_PY=C:\...\Blue365_QMS\py\python.exe
echo   방법 2: python.org 에서 Python 3.11 이상 설치(설치 화면에서 'Add python.exe to PATH' 체크).
echo   ※ 'python' 입력 시 Microsoft Store가 열리면 실제 파이썬이 설치되지 않은 상태입니다.
goto end

:oldpy
echo [오류] 파이썬 3.11 이상이 필요합니다. 새 버전을 설치하거나 QMS 패키지의 파이썬(QMS_PY)을 쓰세요.
goto end

:nopip
echo.
echo [오류] 구성요소 설치(pip)에 실패했습니다. 사내망이 인터넷 설치를 막는 경우가 많습니다.
echo   해결: 이미 설치한 QMS 패키지의 파이썬을 쓰면 설치 없이 실행됩니다.
echo       set QMS_PY=C:\...\Blue365_QMS\py\python.exe
echo     를 입력한 뒤 같은 창에서 RUN_CODE.bat 을 다시 실행하세요. (또는 IT에 pip 사내 저장소 문의)
goto end

:failrun
echo.
echo [오류] 실행 중 문제가 생겼습니다. 위 빨간 글씨(오류 내용)를 복사하거나 화면을 캡처해 담당자에게 보내 주세요.

:end
echo.
pause
exit /b 1
