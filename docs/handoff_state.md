# 핸드오프 상태 (Handoff State)

> ⭐️ 새 세션 시작 시 Main-Agent가 **가장 먼저** 읽는 파일입니다. (CLAUDE.md §0 / §5)
> 주요 단계 완료 시, 또는 사용자가 "handoff / 핸드오프 / 저장해줘" 요청 시 갱신합니다.

- **최종 업데이트**: 2026-07-23 (데이터 로컬 전용 정책 반영 + 로더·검증게이트 뼈대 완료)
- **현재 파이프라인 단계**: `1. Data-Analyst 준비` (코드 뼈대 완료, 데이터 업로드 대기)
- **현재 활성 Agent**: `[Data-Analyst]`
- **데이터 보관 정책**: 🔒 **로컬 전용** — GitHub 커밋 금지 (`.gitignore`), 필요 시 `BLUE365_DATA_DIR` 환경변수

---

## 1. 완료 작업 요약 (Done)
- 프로젝트 저장소 초기 구조 생성 (data/ src/ notebooks/ docs/ 등)
- 기존 Streamlit+OpenAI 챗봇 스캐폴드 제거
- `CLAUDE.md` (프로젝트 헌법) 작성 + 운영규칙 보강 (성공기준·infeasibility·검증게이트·핸드오프 커밋)
- 데이터 분석/ML 의존성(`requirements.txt`) 설정
- **데이터 로더 뼈대** (`src/data/loader.py`): `inspect_excel`/`inspect_raw_dir`(스키마 미확정 정찰용), `load_source`/`load_all_sources`(스키마 확정 후 로딩). 파일명 미설정 시 지어내지 않고 안전 차단.
- **검증 게이트** (`src/data/validation.py`): CaO 범위(0~100%)·음수/0 물량·Key 결측·Key 중복·공정 시간역전(광산≤OSP≤야드) 검사. ERROR/WARNING 리포트.
- **설정 주도 구조** (`config/paths.py`, `config/schema.py`): 경로 중앙관리 + SourceSpec(MINE/OSP/YARD 컬럼 플레이스홀더) + 목표 TARGET(44.6±0.5).
- **단위 테스트** (`tests/test_validation.py`): 11개 전부 통과 (`python -m pytest tests/`).

## 2. 핵심 데이터 스키마 & 주요 변수 (Schema)
- 아직 실데이터 미확보. 상세는 `docs/data_schema.md` 참조.
- **확정 필요 항목**:
  - [ ] 광산(XRF/감마레이) 데이터 컬럼 및 식별자
  - [ ] OSP(적재 위치·물량) 데이터 컬럼 및 식별자
  - [ ] 야드(CNA) 데이터 컬럼 및 식별자
  - [ ] 공정 간 Join Key (작업일자·로트번호·차량번호·구역코드 등)
  - [ ] Time-Lag 규칙 (광산→OSP→야드 이송/적재 시간차)
  - [ ] 물량 단위(Ton), 품위 단위(%)

## 3. 현재 직면한 문제점 / 미해결 이슈 (Open Issues)
- 실데이터 미업로드 상태. 로컬 `data/raw/`에 엑셀 필요.
- **데이터 보관 정책 확정: 로컬 전용(Local-Only).** 저장소는 Public 유지하되 `data/`·`models/`·`outputs/predictions/` 실파일은 GitHub에 절대 커밋하지 않는다(`.gitignore`). git에는 코드·문서·스키마만. (Private 전환/데이터 커밋 방식은 폐기)
- `config/schema.py`의 MINE/OSP/YARD 컬럼이 전부 미확정(None). EDA 후 채워야 로더·검증이 실제 컬럼에 작동.

## 4. 다음 행동 (Next Action) ⭐️
- **담당 Agent**: `[Data-Analyst]`
- **행동**: 사용자가 데이터를 로컬 `data/raw/`에 두거나 채팅에 첨부하면 → ① `inspect_raw_dir()`로 파일·시트·컬럼·dtype·결측 파악 → ② `config/schema.py`의 SourceSpec + `docs/data_schema.md` 채우기(Join Key·Time-Lag 규칙 포함) → ③ `validate_source()`로 검증 게이트 실행 → ④ 초기 EDA/트렌드 시각화.
- **주의**: 데이터·모델·예측결과 파일은 **원격 커밋 금지**. 커밋 전 `git status`로 확인.
- **선행 조건**: 광산(XRF/감마레이)·OSP(적재/물량)·야드(CNA) 3종 데이터. 없으면 사용자에게 요청.
