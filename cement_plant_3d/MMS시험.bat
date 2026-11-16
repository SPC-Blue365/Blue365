@echo off
chcp 65001 > nul
cd /d "%~dp0"
rem MMS 시험: 로그인 → 값 요청 형식 찾기 → 매칭표(MMS_매칭표.xlsx)의 '매칭' 항목 값이 오는지 확인. 서버는 켜지 않습니다.
python server.py --mms-test
pause
