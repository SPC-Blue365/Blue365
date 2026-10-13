# HANDOFF — 새 세션 인수인계 (먼저 이 파일을 끝까지 읽고 시작할 것)

> 목적: 이전 대화를 처음부터 다시 하지 않도록 현재 상태·결정·제약·다음 작업을 모았다.
> 저장소 `spc-blue365/blue365`, **작업 브랜치 `ccr-4c0c953d-ll1jyd`**(직전 커밋 `c3c40ac`, 이번 작업은 그 위에 커밋됨 — `git log` 로 확인). 이 브랜치에만 커밋·푸시한다.
> **사용자가 명시적으로 요청하기 전에는 PR을 만들지 않는다.**

## 1. 사용자
- 시멘트 공장 **품질관리 담당자**. 한국어로 답한다. 꼼꼼하고 자세히, **사실 / 추정 / 경험칙 구분 표기**, 수치·규격은 출처 제시.
- 전문용어(C3S·LSF·SM·IM·f-CaO·KS·킬른) 그대로 사용 가능. 결과물은 **경영진 보고용이라 이해하기 쉽고 근거가 명확**해야 한다.
- 보고서는 PPT, 데이터 정리는 엑셀, 표·서식 일관. 품질 이상 질문은 ①현상 정량화 ②5축 원인(화학·원료·공정·설비·시험오차) ③확인 방법 ④단기/근본 대책 ⑤KS 대비 평가 순서.

## 2. 지금까지 만든 것 (모두 이 저장소에 있음, 테스트 120건 통과)
| 산출물 | 위치 | 비고 |
|---|---|---|
| 통합 QMS(설치형, Streamlit) | `streamlit_app.py`, `app_pages/`, `qms/` | 모니터링·SPC·알림·원인진단·강도예측·배합설계·6가크롬·LIMS 연동·AI(LLM) |
| 배합 설계 다원료 | `qms/rawmix.py`, `app_pages/rawmix.py` | **구분별 후보 최대 5종 수동 입력**(설치형·대시보드 양쪽) |
| LIMS 연동(설치형) | `qms/lims.py`, `app_pages/lims.py`, `docs/LIMS_연동_준비서.xlsx` | SQL/REST/파일(긴 형식·가로형), 매핑표 엑셀 가져오기, 워터마크 증분 동기화 |
| Windows 오프라인 설치 패키지 | `scripts/build_windows_package.py`, `packaging/windows/` | 휴대용 Python 3.13.16(NuGet)+구성요소 사전설치, 분할 ZIP 6개, 1번만 교체하는 업데이트 |
| 태블릿 열람 | `qms/share.py`, `qms/ui.py` | 공유 실행 URL·QR, 태블릿 보기(그래프 손가락 스크롤) |
| **오프라인 HTML 대시보드(무설치)** | `dashboard/src/{index.html,styles.css,chem.js,app.js}`, `scripts/build_dashboard.py`, `scripts/export_dashboard_data.py` | 단일 파일 2.2MB, `python scripts/build_dashboard.py` → `dist/dashboard/Blue365_QMS_대시보드.html` |
| IT 도입 검토 요청서 | `docs/사내망_도입_IT검토요청서.md` | 해시값은 빌드마다 바뀌므로 재빌드 후 갱신 필요 |
| 문서 | `README.md`(전체 안내), `packaging/windows/README.txt`(설치 안내) | |

## 3. 사용자의 현재 환경·결정 (중요)
- 회사 보안 정책으로 **ZIP/EXE 다운로드·설치가 막힘**. 사내망 PC에서는 **단일 HTML 파일**을 쓰기로 함. **설치형 앱은 나중에 IT와 해결해서 쓸 것이므로 반드시 유지**한다.
- **보안 우회는 도와주지 않는다**(확장자 변경·암호화·분할 반입·개인 원격접속 등). 정식 경로는 IT 승인(요청서 `docs/사내망_도입_IT검토요청서.md`). 사용자가 제안한 개인 원격 데스크톱(구글 등)도 같은 이유로 거절했고 사용자가 수용함.
- 이 환경(클라우드)은 **사내망·LIMS에 접속할 수 없다**. LIMS 직접 연동은 사용자가 어렵다고 판단했고, **엑셀을 대시보드에 업로드하는 방식**으로 간다.
- 사용자는 실제 LIMS 엑셀을 한 번도 공유하지 않았다 → **열 이름·양식을 추측해서 만들어 온 것이 인식률 저하의 근본 원인**이다.

## 4. 진행 중 / 다음 작업 ★
**완료(이번 세션): 엑셀 구조 자동 분석** — `dashboard/src/ingest.js`(브라우저·노드 공용 엔진) + `app.js` 불러오기 블록 교체.
- 머리글 줄·그룹(병합) 머리글·단위 줄 탐지, 가로형/세로형(시험 1건=1행) 자동 판별, 열 이름 + **값 범위** + 앞뒤 열 문맥으로 항목 판단, 날짜/시간 분리·엑셀 일련번호·오전/오후·`<0.1` 처리.
- 확실(✅)한 것만 자동 반영. 🔶 추정·❓ 후보 여럿이면 확인 패널 → 확인하면 localStorage 에 기억(같은 양식은 다음부터 자동). 처리 요약(읽은 행·항목·무시한 열·건너뛴 행)은 항상 표시, 조용히 버리지 않음.
- 시험: `tests/js/ingest_test.js`(16건, pytest `test_ingest_engine_node_suite` 로 실행, 총 121건 통과), 브라우저 e2e `tests/js/e2e_dashboard.js`(+`make_fixtures.py`, 수동)로 세로형·2줄 머리글+단위 줄·모르는 열(확인→기억→재업로드 자동)·붙여넣기, 콘솔 오류 0 확인.
- **100%는 약속하지 않았다.** 사용자는 실제 LIMS 엑셀을 아직 공유하지 않음.

**다음 작업**
1. 사용자에게 **실제 LIMS 엑셀의 열 이름 줄 + 값 1~2줄**(숫자는 임의 값 가능)과 "한 줄 = 시험 1건인지 시료 1건인지"를 받아 `tests/`·e2e 회귀 샘플에 추가하고 인식 규칙(`ingest.js` 별칭·RANGES)을 보강한다.
2. (선택, 사용자 확인 후) 설치형 앱 업로드(`app_pages/data.py`, `qms/store.py parse_upload`)에도 같은 자동 인식을 적용.
3. 설치 패키지를 다시 만들면 `docs/사내망_도입_IT검토요청서.md` 의 해시 갱신.

## 5. 개발·검증 방법
- 테스트: `python3.13 -m pytest -q`(120건). 대시보드: `node --check dashboard/src/app.js` → `python3.13 scripts/build_dashboard.py` → Playwright(Chromium `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, `--no-proxy-server`)로 `file://` 열어 확인. JS 계산(`chem.js`)은 Python(`qms/chemistry.py`·`rawmix.py`·`chromium.py`)과 **수치가 같아야 한다**(과거 대조 완료).
- 네트워크: `registry.npmjs.org`·`pypi.org`·nuget 접속 가능, `cdn.jsdelivr.net`·`cdnjs`·`python.org`·`github release`는 프록시가 막음(403).
- Windows 시험은 Wine 9.0(+UCRT 수동 복사)로 했다(새 컨테이너에서는 재설치 필요, 필수 아님).
- 린트: `ruff check --line-length 120 --target-version py311`(기존 코드의 DTZ005·C408 등은 이미 있던 경고, 새 코드에서만 0 유지).
- 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 와 `Claude-Session: https://claude.ai/code/session_01SThQQoxEvTAWtLKryN98as` 를 붙인다. 푸시는 `git push -u origin ccr-4c0c953d-ll1jyd`(네트워크 오류 시에만 2·4·8·16초 재시도).
- 비밀값(DB 비밀번호·메일·API 키)은 절대 커밋하지 않는다(`.streamlit/secrets.toml`은 gitignore).

## 6. 이미 거절·결정된 사항 (다시 논의하지 말 것)
- 보안 우회·개인 원격접속 방식은 불가(사용자 수용).
- 모델 정체성은 코드·커밋·PR 본문에 쓰지 않는다(커밋 트레일러의 Co-Authored-By 줄만 예외로 시스템 지침 따름).
- 모든 수치 기본값(원료 성분·단가·킬른 계수·전환율 등)은 **예시(추정)**이며 공장 실측으로 교체해야 한다고 항상 표시한다.

## 7. 새 세션 첫 메시지 (사용자가 붙여넣을 한 줄)
> HANDOFF.md를 읽고 4번 "진행 중/다음 작업"부터 이어서 진행해줘. 대화를 처음부터 다시 묻지 마.
