# 석회석 광산-야드 품위(CaO) 매칭 및 추적 시스템

석회석 채굴부터 야드 적재까지 전 공정의 **CaO(생석회) 품위 데이터를 매칭**하여, **물류 추적(Tracking)** · **품위 예측** · **운영 모니터링**을 수행하는 하이브리드 데이터/ML 시스템입니다.

## 목표

- **최종 품질 목표**: 야드 적재 CaO 평균 **44.6% (표준편차 0.5 이내)**
- **추적 경로**: 광산(49Q XRF·47Q 감마레이) → OSP 인출(기존·신설 라인) → 야드(기존↔45Q / 신설↔CNA)
- **핵심 과제**: 분절된 공정 데이터의 추적 매칭 + 품위 예측·조기경보 → **변동성 축소(안정화)**

## 빠른 시작

```bash
pip install -r requirements.txt

# 1) 데이터를 로컬에 배치 (data/raw/data_v1.xlsx)
# 2) 전체 파이프라인 원클릭 실행
python scripts/run_all.py                      # 전체 기간
python scripts/run_all.py --start 2026-06-15   # 기간 지정

# 3) 운영 대시보드
streamlit run streamlit_app.py
```

**산출물** (`outputs/`, 로컬 전용)
- `final_report.html` — 임원 발표용 통합 리포트(7탭, 기간 직접설정 가능)
- `monitor_status.html` — 운영 모니터 상태·경보
- `alert_log.csv` — 경보 이력

## 개별 실행

| 명령 | 역할 |
|---|---|
| `python scripts/build_matched_dataset.py` | 검증 게이트 → 추적 매칭 통합셋 |
| `python scripts/train_and_save.py` | 확정 모델(Ridge) 라인별 학습·저장 |
| `python scripts/benchmark_models.py` | **10개 모델 재벤치마크**(데이터 축적 시 최적 모델 재추천) |
| `python scripts/monitor.py` | 모니터 상태·경보 산출 |
| `python scripts/make_final_report.py` | 통합 리포트만 생성 |
| `python -m pytest tests/` | 테스트 40개 |

## 현재 상태 (정직 보고)

- **예측 모델**: Ridge(AR) — 신설/CNA MAE 0.80, 기존/45Q MAE 1.04 (naive 1.3~1.8 대비 개선)
- **한계**: 상류(OSP 인출) → 야드 CaO 상관 0.18로 약함 → 목표 MAE<0.5 미달. **실시간 모니터링·조기경보용으로 유효**하며, 처방적 배합제어는 데이터 축적 후 정밀화.
- **핵심 과제**: 연속 실측 표준편차 1.85~2.26 ≫ 목표 0.5 → 변동성 축소.

## 작업 방식

**Claude Code 멀티에이전트 워크플로우**로 개발됩니다. 운영 원칙·역할·핸드오프 규칙은 [`CLAUDE.md`](./CLAUDE.md)에 정의돼 있습니다.

- 세션 상태: [`docs/handoff_state.md`](./docs/handoff_state.md) (새 세션이 가장 먼저 읽음)
- 데이터 스키마·매칭 규칙: [`docs/data_schema.md`](./docs/data_schema.md)
- 진행 기록: [`docs/session_log.md`](./docs/session_log.md)

> **데이터 보관 = 로컬 전용.** 광산 품위 데이터는 민감정보이므로 GitHub에 **절대 커밋하지 않습니다.**
> `data/`·`models/`·`outputs/` 는 `.gitignore` 처리되며, git에는 코드·문서·스키마만 올라갑니다.
> 저장소 바깥 경로 사용: `export BLUE365_DATA_DIR="/path/to/data"` (자세히는 [`CLAUDE.md` §6.1](./CLAUDE.md))

## 디렉토리 구조

```
config/      경로·스키마 스펙(검증 게이트 계약)
src/data/    정제(clean)·구조정찰(loader)·검증게이트(validation)
src/matching/ 시간인지 매칭·Time-Lag 추정
src/models/  예측(forecast)·벤치마크·공용 데이터셋
src/monitoring/ 경보엔진·모니터·이력
src/optimization/ 배합 최적화 솔버(scipy LP)
src/visualization/ Plotly 차트·리포트 조립
scripts/     실행 진입점 (run_all 외 5종)
docs/        핸드오프·스키마·세션로그·리포트
```
