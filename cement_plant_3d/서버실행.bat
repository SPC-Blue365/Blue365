@echo off
chcp 65001 > nul
cd /d "%~dp0"
rem 팀 공유 서버. 기본: 사내망 사설 IP만 접속 허용.
rem  - 업로드 비밀번호: --key 비밀번호   (권장)
rem  - 접속 대역 좁히기: --allow 192.168.10.0/24
rem  - 공유 폴더 자동 읽기: --watch "\\서버\폴더"
python server.py --port 8365
pause
