@echo off
chcp 65001 > nul
cd /d "%~dp0"
rem 팀 공유 서버 실행. 공유 폴더 자동 읽기: --watch "\\서버\폴더" 를 뒤에 붙이세요.
python server.py --port 8365
pause
