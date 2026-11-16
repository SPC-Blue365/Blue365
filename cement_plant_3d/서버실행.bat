@echo off
chcp 65001 > nul
cd /d "%~dp0"
rem 팀 공유 서버. 기본: 사내망 사설 IP만 접속 + 로그인(관리자 승인) 필수.
rem  - 처음 실행 후 이 PC 브라우저에서 http://localhost:8365 로 관리자 계정을 만드세요.
rem  - 업로드: 편집 권한 + 본인 비밀번호 재확인 (기본). 공통 암호를 더 걸려면 --key 암호
rem  - 접속 대역 좁히기: --allow 192.168.10.0/24
rem  - 자동 백업(하루 1회)을 다른 디스크·공유 폴더에: --backup-dir "\\서버\백업\Blue365"
rem  - 공유 폴더 자동 읽기: --watch "\\서버\폴더"
rem  - 출하속보 자동 읽기: --sokbo-watch auto = 구글 드라이브의 'Blue365 출하속보' 폴더를 자동으로 찾음
rem      (폴더를 직접 지정하려면 auto 대신 "G:\내 드라이브\Blue365 출하속보" 처럼 큰따옴표로)
rem  - MMS 연결: --mms = 같은 폴더의 MMS_매칭표.xlsx 에서 상태가 '매칭'인 항목을 30초마다 읽음 (먼저 MMS설정.bat · MMS시험.bat)
python server.py --port 8365 --sokbo-watch auto --mms
pause
