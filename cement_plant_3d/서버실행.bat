@echo off
chcp 65001 > nul
cd /d "%~dp0"
rem 팀 공유 서버. 기본: 사내망 사설 IP만 접속 + 로그인(관리자 승인) 필수.
rem  - 처음 실행 후 이 PC 브라우저에서 http://localhost:8365 로 관리자 계정을 만드세요.
rem  - 업로드: 편집 권한 + 본인 비밀번호 재확인 (기본). 공통 암호를 더 걸려면 --key 암호
rem  - 접속 대역 좁히기: --allow 192.168.10.0/24
rem  - 자동 백업(하루 1회)을 다른 디스크·공유 폴더에: --backup-dir "\\서버\백업\Blue365"
rem  - 공유 폴더 자동 읽기: --watch "\\서버\폴더"
python server.py --port 8365
pause
