"""Blue365 통합 품질관리 시스템(QMS) 핵심 패키지.

모듈 구성
---------
chemistry   시멘트 화학 계산 (LSF·SM·IM·Bogue 광물·액상량)
standards   관리항목 정의, KS L 5201 규격, 사내 관리기준
demo        데모용 공정·품질 데이터 생성기 (인과관계를 반영한 시뮬레이션)
store       SQLite 저장소 및 엑셀 업로드 처리
spc         관리도·판정규칙·공정능력지수
alerts      규격/관리기준/SPC 이탈 → 알림 이벤트 생성
knowledge   원인 가설 지식베이스 (화학·원료·공정·설비·시험오차 5축)
diagnosis   증거 기반 원인 우선순위화 및 5단계 분석 보고
prediction  28일 압축강도 조기 예측
notify      이메일·웹훅 알림 발송
reports     엑셀·PPT 보고서 생성
rawmix      원료 배합 최적화 · 클링커/XRD/f-CaO 예측 · 생료→클링커 실적 검증 · 배합 설계서
strength    재령별 강도·응결 예측(경험칙 사전정보 리지) · 제어 최적화 · 조치 지식베이스
chromium    시멘트 6가크롬 물질수지 · 환원제 투입량 · 전환율 보정 · 저감 지식베이스 · 평가표
lims        LIMS 연동(SQL·REST·파일) · 시험코드 매핑 · 증분 동기화
llm         AI 솔루션 보고서(Claude API) — 계산 결과·지식베이스 근거, 사실/추정 구분
"""

__version__ = "0.2.0"
