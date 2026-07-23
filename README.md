# 석회석 광산-야드 품위(CaO) 매칭 및 추적 시스템

석회석 채굴부터 야드 적재까지 전 공정의 **CaO(생석회) 품위 데이터를 매칭**하여, **물류 추적(Tracking)** 및 **배합 최적화**를 수행하는 하이브리드 데이터/ML 시스템입니다.

## 목표

- **최종 품질 목표**: 야드 적재 완료 후 평균 CaO 품위 **44.6% (표준편차 0.5 이내)**
- **추적 경로**: 광산(XRF·감마레이) → OSP(품위별 적재/물량) → 야드(CNA 실시간 분석기)
- **핵심 과제**: 공정별 분절 데이터의 매칭 추적 알고리즘 + 하이브리드 ML(예측 · 최적 배합) 구축

## 작업 방식

이 저장소는 **Claude Code 멀티에이전트 워크플로우**로 개발됩니다.
운영 원칙·역할·핸드오프 규칙은 [`CLAUDE.md`](./CLAUDE.md)에 정의되어 있습니다.

- **Data-Analyst** → **Matching-Agent** → **ML-Engineer** 순차 파이프라인
- 상태는 [`docs/handoff_state.md`](./docs/handoff_state.md)에 저장되어 세션 간 이어집니다.
- 데이터 스키마·매칭 규칙은 [`docs/data_schema.md`](./docs/data_schema.md)에 기록됩니다.

## 시작하기

```bash
pip install -r requirements.txt
```

이후 분석할 엑셀 데이터를 로컬 `data/raw/` 폴더에 두면 병합(Merge) 및 EDA를 시작합니다.

> **데이터 보관 = 로컬 전용.** 광산 품위 데이터는 민감정보이므로 GitHub(원격)에는 **절대 커밋하지 않습니다.**
> `data/`·`models/`·`outputs/predictions/` 는 `.gitignore`로 제외되고, git에는 코드·문서·스키마만 올라갑니다.
> 데이터를 저장소 바깥 로컬 경로에 두려면 환경변수로 지정하세요:
> ```bash
> export BLUE365_DATA_DIR="/path/to/local/data"
> ```
> 자세한 라우팅 규칙은 [`CLAUDE.md` §6.1](./CLAUDE.md)을 참조하세요.

## 디렉토리 구조

전체 구조와 각 폴더의 담당 역할은 [`CLAUDE.md` §6](./CLAUDE.md)를 참조하세요.

```
data/        원본→중간→처리완료→외부참조 데이터 계층
src/         파이프라인 단계별 소스코드 (data/matching/features/models/optimization/...)
notebooks/   EDA·매칭·모델링·최적화 실험
docs/        핸드오프 상태 · 데이터 스키마 · 리포트 · 선행연구
outputs/     생성된 차트·예측 결과
models/      학습된 모델 아티팩트
```
