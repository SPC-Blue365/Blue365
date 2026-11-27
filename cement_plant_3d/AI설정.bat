@echo off
chcp 65001 > nul
cd /d "%~dp0"
rem Blue365 AI 질의 설정 (관리자 전용 · Claude API)
rem  1) Anthropic 공식 Python SDK 설치(이미 있으면 최신으로)  2) API 키·월 사용 한도 저장 (data/ai.json, 이 PC에서만 풀리게 암호화)
rem  사내 문서는 data\ai_docs 폴더에 넣으면 AI가 근거로 씁니다 (.md .txt .csv .pdf)
python -m pip install --upgrade anthropic
python server.py --ai-setup
pause
