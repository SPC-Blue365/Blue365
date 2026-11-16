@echo off
chcp 65001 > nul
cd /d "%~dp0"
rem MMS 연결 설정: MMS 주소·아이디·비밀번호를 이 PC(data\mms.json)에만 저장합니다. 로그인 시험 후 저장.
rem  - 비밀번호는 화면에 보이지 않게 입력합니다. Windows 암호화로 이 PC·이 Windows 사용자만 풀 수 있습니다.
rem  - 서버 창(서버실행.bat)을 켤 Windows 계정으로 실행하세요.
python server.py --mms-setup
pause
