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

rem ── 2. 파이썬 찾기 ──
rem   QMS_PY(직접 지정) → 설치한 QMS 패키지의 파이썬(코드 폴더 옆·C:\Blue365_QMS·다운로드·바탕화면·문서 폴더 자동 검색)
rem   → py 런처 → python. 설치 패키지 파이썬은 구성요소가 모두 들어 있어 인터넷·pip 설치가 필요 없다.
set "PY="
set "QMS_HOME="
if defined QMS_PY if exist "%QMS_PY%" set "PY=%QMS_PY%"
if not defined PY echo   설치한 QMS 패키지를 찾는 중...
if not defined PY call :findqms "%~dp0.."
if not defined PY if exist "C:\Blue365_QMS\py\python.exe" set "QMS_HOME=C:\Blue365_QMS"
if not defined PY if not defined QMS_HOME call :findqms "%USERPROFILE%\Downloads"
if not defined PY if not defined QMS_HOME call :findqms "%USERPROFILE%\Desktop"
if not defined PY if not defined QMS_HOME call :findqms "%USERPROFILE%\Documents"
if not defined PY if not defined QMS_HOME if defined OneDrive call :findqms "%OneDrive%"
if not defined PY if not defined QMS_HOME call :findqms "%~dp0..\.."
if not defined PY if defined QMS_HOME set "PY=%QMS_HOME%\py\python.exe"
set "PYFLAGS="
if defined QMS_HOME set "PYFLAGS=-E -s"
if not defined PY (
  py -3 -c "import sys" >nul 2>nul && set "PY=py"
)
if not defined PY (
  python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY goto nopy
set PYRUN="%PY%"
if "%PY%"=="py" set "PYRUN=py -3"
rem 경로에 괄호가 있어도(예: "…_1of6 (1)") 끊기지 않도록 if 줄 안에서 경로를 펼치지 않는다
if not defined QMS_HOME goto showpy2
echo   파이썬: 설치한 QMS 패키지 - %QMS_HOME%
goto showpy3
:showpy2
echo   파이썬: %PY%
:showpy3
%PYRUN% %PYFLAGS% -c "import sys; print('   Python', sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto oldpy

rem ── 3. 구성요소 확인 → 없으면 설치(인터넷 또는 사내 pip 저장소 필요) ──
%PYRUN% %PYFLAGS% -c "import streamlit, pandas, numpy, scipy, plotly, openpyxl, pptx; v = tuple(int(x) for x in streamlit.__version__.split('.')[:2]); raise SystemExit(0 if v >= (1, 55) else 1)" >nul 2>nul
if not errorlevel 1 goto drivers
if defined QMS_HOME goto brokenqms
echo.
echo   구성요소가 없거나 오래되어 설치합니다(처음 1회, 수 분 소요)...
%PYRUN% -m pip install -r requirements.txt
if errorlevel 1 goto nopip

rem ── 3-1. LIMS DB 드라이버(pymssql, oracledb, psycopg2, PyMySQL): 없으면 하나씩 설치, 실패해도 실행은 계속 ──
:drivers
if defined QMS_HOME goto data
%PYRUN% -c "import sqlalchemy, pymssql, oracledb, psycopg2, pymysql" >nul 2>nul
if not errorlevel 1 goto data
echo.
echo   LIMS DB 드라이버를 설치합니다(처음 1회)...
%PYRUN% -c "import sqlalchemy" >nul 2>nul || %PYRUN% -m pip install "SQLAlchemy>=2.0"
%PYRUN% -c "import pymssql" >nul 2>nul || %PYRUN% -m pip install "pymssql>=2.3"
%PYRUN% -c "import oracledb" >nul 2>nul || %PYRUN% -m pip install "oracledb>=2.0"
%PYRUN% -c "import psycopg2" >nul 2>nul || %PYRUN% -m pip install "psycopg2-binary>=2.9"
%PYRUN% -c "import pymysql" >nul 2>nul || %PYRUN% -m pip install "PyMySQL>=1.1"
echo   설치하지 못한 드라이버는 화면 LIMS 연동 - 연결 설정의 '드라이버 설치' 버튼으로 다시 시도할 수 있습니다.

rem ── 4. 데이터 폴더: 설치 앱의 데이터를 함께 쓸지(처음 1회 묻고 기억) ──
:data
if defined QMS_DATA_DIR goto showdata
if not defined QMS_HOME goto showdata
if not exist "%QMS_HOME%\data\" goto showdata
set "CHOICE_FILE=%~dp0data\.run_code_data"
set "USE_QMS_DATA="
if exist "%CHOICE_FILE%" set /p USE_QMS_DATA=<"%CHOICE_FILE%"
if defined USE_QMS_DATA goto applydata
echo.
echo   설치한 QMS의 데이터(출하시멘트 기록·기준·LIMS 설정)를 이 코드 실행에서도 함께 쓸까요?
echo     1 = 함께 쓰기(권장, 같은 화면·같은 자료)     2 = 이 코드 폴더의 별도 데이터(연습·시험용)
choice /c 12 /t 20 /d 1 /n /m "  번호 [1/2] (20초 뒤 1): "
if errorlevel 2 (set "USE_QMS_DATA=2") else (set "USE_QMS_DATA=1")
if not exist "%~dp0data\" mkdir "%~dp0data"
> "%CHOICE_FILE%" echo %USE_QMS_DATA%
echo   (선택을 기억합니다. 바꾸려면 data\.run_code_data 파일을 지우세요)
:applydata
if "%USE_QMS_DATA%"=="1" set "QMS_DATA_DIR=%QMS_HOME%\data"
:showdata
if not defined QMS_DATA_DIR goto showdata2
echo   데이터: %QMS_DATA_DIR%
goto showdata3
:showdata2
echo   데이터: %~dp0data - 이 코드 폴더 전용
:showdata3
if "%USE_QMS_DATA%"=="1" echo   ※ 설치 앱과 같은 데이터를 쓰므로 설치 앱 2_RUN 과 동시에 켜지 마세요.

:run
echo.
echo   시작합니다. 브라우저가 열리지 않으면 http://localhost:8501 을 직접 여세요. (종료: 이 창 닫기 또는 Ctrl+C)
echo.
rem 기본은 내 PC 전용(127.0.0.1). 사내망 공유: RUN_CODE.bat --server.address 0.0.0.0
%PYRUN% %PYFLAGS% -m streamlit run streamlit_app.py --server.address 127.0.0.1 --browser.gatherUsageStats false %*
if errorlevel 1 goto failrun
exit /b 0

rem ── 하위 함수: 폴더 아래에서 설치한 QMS(Blue365_QMS\py\python.exe)를 찾는다(이름순 마지막 = 보통 최신 버전) ──
:findqms
if not exist "%~1\" exit /b 0
for /d /r "%~1" %%D in (Blue365_QMS) do (
  if exist "%%D\py\python.exe" if exist "%%D\tools\qms_launcher.py" set "QMS_HOME=%%D"
)
exit /b 0

:nocode
echo [오류] 이 폴더에 QMS 코드가 없습니다(streamlit_app.py, qms, app_pages 폴더 필요).
echo   - GitHub 첫 화면(main 브랜치)에서 받으면 'Chatbot' 예제만 들어 있습니다.
echo   - 아래 주소로 받으세요(ZIP을 풀고 그 안의 RUN_CODE.bat 실행):
echo     https://github.com/SPC-Blue365/Blue365/archive/refs/heads/ccr-4c0c953d-ll1jyd.zip
goto end

:nopy
echo [오류] 파이썬을 찾지 못했습니다.
echo   방법 1(권장, 인터넷 불필요): QMS 설치 패키지(1~6번 ZIP)를 먼저 설치하세요. 다운로드·바탕화면·문서 폴더나
echo     C:\Blue365_QMS 에 있으면 자동으로 찾습니다. 다른 곳이면 아래처럼 위치를 지정한 뒤 같은 창에서 다시 실행하세요.
echo       set QMS_PY=C:\...\Blue365_QMS\py\python.exe
echo   방법 2: python.org 에서 Python 3.11 이상 설치(설치 화면에서 'Add python.exe to PATH' 체크).
echo   ※ 'python' 입력 시 Microsoft Store가 열리면 실제 파이썬이 설치되지 않은 상태입니다.
goto end

:oldpy
echo [오류] 파이썬 3.11 이상이 필요합니다. 새 버전을 설치하거나 QMS 패키지의 파이썬(QMS_PY)을 쓰세요.
goto end

:brokenqms
echo [오류] 설치한 QMS 패키지의 구성요소를 불러오지 못했습니다.
echo   위치: %QMS_HOME%
echo   그 폴더의 1_SETUP.bat 을 먼저 실행해 설치를 끝내세요(2~6번 ZIP 필요).
goto end

:nopip
echo.
echo [오류] 구성요소 설치(pip)에 실패했습니다. 사내망이 인터넷 설치를 막는 경우가 많습니다.
echo   해결: QMS 설치 패키지를 설치하면 그 파이썬을 자동으로 써서 설치 없이 실행됩니다.
echo     (또는 set QMS_PY=C:\...\Blue365_QMS\py\python.exe 입력 후 같은 창에서 다시 실행, IT에 pip 사내 저장소 문의)
goto end

:failrun
echo.
echo [오류] 실행 중 문제가 생겼습니다. 위 빨간 글씨(오류 내용)를 복사하거나 화면을 캡처해 담당자에게 보내 주세요.

:end
echo.
pause
exit /b 1
