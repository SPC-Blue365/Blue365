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

**완료(2차): 사용자가 실제 LIMS 출하시멘트 엑셀을 제공함** → 🚢 출하시멘트 탭 구현(`dashboard/src/ship.js` + `app.js` ⑦ 블록, 탭 id `ship`, `index.html` 섹션 필요).
- 실제 파일 구조(883행×66열, 머리글 1줄, 1행=채취일 1건, 품명 '1종시멘트 벌크'): **값 0=미시험**, 종결시간 'HH:MM'·초결 숫자 문자열, TA=Na₂O+0.658K₂O(검증), 비고=선박명(잡음 많음: 마침표·공백·'수성3'/'수성3호'·괄호 안 쉼표·쉼표 없이 붙은 이름·오타). 1모선=단독 시험, 2모선 이상=평균.
- 사용자가 중요하다고 한 항목(17개)만 핵심으로 판정, 나머지 숫자 열은 상세 항목 목록에서 선택 가능. 판정 기준: 최근 10건 중 기준 이탈🔴 / 평균±3σ 이탈🟠 / 9점 연속 치우침🟡(참고). 석회석·첨가재 비율은 설정값이라 판정 제외.
- KS L 5201 기준값(강도 3/7/28일 12.5/22.5/42.5, Blaine 2800, MgO 5.0, SO₃ 3.5, LOI 5.0, 종결 600분)은 **웹 검색으로 원문을 확인하지 못한 추정치**로 UI에 그렇게 표시, 사용자 수정 가능(localStorage). Cl 등 규격값은 넣지 않음.
- 실제 파일은 회사 자료라 **저장소에 넣지 않음**. 시험은 합성 자료(`tests/js/ship_test.js`, `make_ship_fixture.py`, `e2e_ship.js`). pytest 123건 통과.
- 실제 파일 점검 결과(참고): 2024-01-02~2026-10-11 883건, 선박 13척(수성1/2/3/5/6호·리나·삼표1/2/3/5호·정진·해진·유진), 비고 불확실 10건 단독 분석 제외, 28일 강도 0 24건, 최근 6개월 3σ 이탈 항목: Al₂O₃·주도·Flow.

**완료(3차): 사용자 요청 — "대시보드에 업로드하지 말고 설치 앱에 업데이트"** → 설치형(Streamlit)에 출하시멘트 기능 구현.
- `qms/shipment.py`(형식 자동 인식·정규화·SQLite `data/shipment.db` 저장·연도별 기준·판정·혼합재 분석), `qms/ui_ship.py`(업로드 패널), `app_pages/shipment.py`(🚢 출하시멘트(1종) 화면), `app_pages/data.py`(출하시멘트 형식이면 전용 저장으로 연결), 시험 `tests/test_shipment.py`. 대시보드(HTML)의 🚢 탭은 그대로 두었다(추가 개발 안 함; 비율 0 처리 버그만 수정).
- **사용자 확정 사항(반드시 유지)**: 단위 Cl=ppm, 45㎛=잔사 %, 주도=%. **‘저염’ 표기 = 저염 제품 출하**(제품구분 일반/저염/혼재로 분리). **선박별로 값을 추정(분해)하지 말 것**(1모선=단독 시험, 2모선↑=평균값으로만 구분). 선박별 **양하지 자료는 나중에 사용자가 올릴 예정** → 비고 괄호 주석(부산·평택 등)을 `dest_hint` 로 보관, 연결 기능은 그때 구현.
- **관리기준은 사용자가 수동 입력, 연도별로 바뀜**: `data/ship_standards.json`(연도→항목→KS/사내 하·상한·목표). 채취일의 연도 기준으로 판정, 미저장 연도는 직전 연도 승계. 사내 기준 초기값은 비어 있음(KS 참고값만 미리 입력: 강도 3/7/28일 12.5/22.5/42.5, Blaine 2800, MgO 5.0, SO₃ 3.5, LOI 5.0, 종결 600분 — `qms/standards.py` 문서에 있는 웹 확인값, 원문 대조 권장).
- **사용자 제공 도메인 지식(분석에 사용)**: 혼합재(=석회석비율+첨가재비율) 투입량이 줄면(예: 10%→8%·7%·5%) 클링커 비율이 올라 강도에 영향. 실제 파일의 혼합재 합계는 10/8/7/6/5.5/5%로 변동. 실제 자료 점검: 혼합재 +1%p당 28일 강도 약 −0.8 MPa(첨가재 종류·Blaine·SO₃ 보정, R²≈0.35, 추정), 석회석은 1일 강도에는 오히려 +(충전재 효과, 경험칙). `S.MIX_KNOWLEDGE`, `mix_changes`, `mix_effect` 참고.
- 실제 파일 점검(참고): 883건(2024-01-02~2026-10-11), 선박 13척, 비고 불확실 10건(오타·수분 표기 등), 저염 11건(Cl 평균 약 260 ppm vs 일반 약 530), 28일 강도 0 24건. 실제 파일은 회사 자료라 저장소에 없음.
- pytest 133건 통과. Windows 패키지 재빌드 완료(`Blue365_QMS_win64_v2026.10.13_1of6.zip`, 2~6번 구성요소 ZIP은 이전과 해시 동일 → **1번 ZIP만 교체**). IT 요청서 해시 갱신함.

**완료(4차): 설치형 앱 전체 화면 디자인 적용(사용자 선택: 시안 A+B 혼합, 색상은 포털과 동일, 모든 화면 한 번에)** — 사내 포털 스타일(상단 메뉴·남색 제목 띠·카드·탭 머리글).
- `qms/theme.py`(CSS, 매 실행 `apply_theme()`), `assets/logo.svg·icon.svg`(자체 글자 로고, 포털 로고 사용 안 함), `.streamlit/config.toml` 테마(밝은 배경·진한 파랑), `streamlit_app.py` 상단 메뉴(`st.navigation(position="top")`, 평면 14개), `qms/ui.py page_header(ctx, title)` 가 모든 화면 맨 위 제목 띠(오늘 날짜·제목·데이터 기간·최근 알림 + 🛠 도구/📲 접속 팝오버)를 그린다. 기존 `sidebar()` 는 제거(새로고침·태블릿 보기·접속 안내는 팝오버로 이동) → 시험(`tests/test_tablet.py`)은 `at.toggle` 로 갱신.
- 선택자는 Streamlit 1.65 DOM 기준(`data-testid="stTab"`, `role=tablist`, `.st-key-qms_hero`). Streamlit 업그레이드 시 `qms/theme.py` 확인.
- 설치 패키지 반영 완료(사용자 승인 후 재빌드): `Blue365_QMS_win64_v2026.10.13_1of6.zip`(SHA-256 ea4c0895…7797), 2~6번 구성요소 ZIP은 해시 동일 → **1번 ZIP만 교체**. IT 요청서 해시 갱신함. 아직 실제 Windows PC에서의 화면 확인은 못 함(사용자 확인 필요).

**완료(5차): 선박별 양하지 자동 연결 + 설치 파일 재작성(사용자: "실행이 안돼")**
- `qms/ship_dest.py`(+ `ship_dest.db`): 선박별 양하지 = ① 운항(양하지) 기록 파일[일자·선박·양하지, ±1일] → ② LIMS 비고 괄호(선박 바로 뒤, `ship_hints`) → ③ 선박 기본 양하지(화면 입력). 불러올 때 계산하므로 기록·기본값을 바꾸면 모든 출하 기록이 자동 재연결. 추정·분해 없음(양하지 다른 배가 섞이면 ‘복수 양하지’). 화면 `🚢 출하시멘트 > ⚓ 양하지`, 필터 ‘양하지’, `데이터 관리` 업로드, `qms_monitor.py --import-dir` 자동 반영. 사용자는 실제 운항·양하지 파일을 아직 주지 않음(열 이름 자동 인식으로 대응).
- **실행 불가 진단**: Wine 9.0(+ .NET Core 2.2 NuGet의 ucrtbase.dll, `WINEDLLOVERRIDES=ucrtbase=n,b`, 출력은 `| cat` 으로 받아야 함)으로 6개 ZIP을 새 폴더에 풀어 setup(4단계·14화면 시험)·run(서버 기동·브라우저 표시)까지 **정상** → 사용자 PC 환경(1번 ZIP만 받아 새로 설치, 압축 미해제, 보안 차단 등) 문제로 추정. 원인 미확정. 보강: 로고 SVG→PNG(`assets/*.png`, 절대 경로, 실패해도 실행), 실행 실패 시 서버 기록 30줄을 창에 표시. 사용자에게 실패 시 logs 내용 요청.
- 전체 패키지 재빌드: 1번 `5ad72d9a…26c9`, 2~6번은 이전과 해시 동일. 6개 전부 전달.

**완료(6차): 사용자 9_CHECK 결과로 설치 실패 원인 확인·수정** — 결과: 2~6번 미설치, 포트 8501에 다른 위치의 이전 QMS 실행 중, 1번이 `Downloads\Claude_project\설치파일\Blue365_QMS_win64_..._1of6\Blue365_QMS` 에 풀림.
- 원인(추정, 유력): 예전 설치 프로그램은 8501에 QMS가 응답하면 '실행 중'으로 보고 **설치를 중단** → 다른 위치 이전 설치본 때문에 새 설치가 시작도 못 함. 수정: `tools/server.json`(포트·PID) 잠금으로 **이 설치본의 서버일 때만 중단**, 다른 설치본이면 경고 후 계속, 실행은 빈 포트(8502…).
- 구성요소 ZIP 탐색 보강: 설치 폴더 상위 3단계·다운로드·바탕화면·문서의 하위 3단계까지, **따로 압축 해제한 구성요소 폴더도 찾아 합침**(`find_extracted_part`·`merge_extracted`, 순수 파이썬 복사).
- Wine 재현(한글 경로 '설치파일', 1번 하위 폴더, 2·3번 ZIP, 4~6번 압축 해제, 8501에 다른 QMS): 설치 4단계·14화면 정상, 8502로 실행·화면 표시 확인. Wine 시험 팁: `LANG=C.UTF-8`(한글 경로), ucrtbase 덮어쓰기, 출력은 `| cat`.

**완료(7차, 2026-10-13) — 사용자 요청 3가지**
1. [x] 3_RUN_SHARE 실행 후 앱 디자인이 바뀌었다는 문제 확인 — Wine 공유 모드(사내 IP 접속)에서 새 디자인 그대로 → 다른 위치의 이전 설치본 화면이 열린 것으로 추정. 🛠 도구에 버전·설치 위치 표시 추가(Wine 공유 모드 재현, 다른 위치의 이전 설치본이 열렸을 가능성 → 화면에 설치 위치·버전 표시)
2. [x] 항목을 골라 그래프로 보기(📉 그래프 보기 화면, 종합 현황 강도 그래프 재령·기간 선택): 출하시멘트(강도 1·3·7·28일 등)·공정 데이터 모든 항목 다중 선택, 기간 설정, 집계·이동평균·기준선, 보기 저장(`data/chart_views.json`)
3. [x] 용어·제목 직접 수정·저장(⚙️ 설정 → ✏️ 용어·제목): 메뉴 이름·화면 제목·항목 이름·단위(`data/labels.json`), 설정 화면에서 편집 즉시 반영
4. [x] 시험(141개 통과)·화면 캡처·1번 ZIP 재빌드(`68225e53…717a`, 2~6번 해시 동일 → 1번만 교체)·Wine 업데이트 설치 재현(이전 설치본 위에 덮어쓰기 → 15화면 정상)·전달
- 사용자 지시: 한도가 걸려 멈췄다가 풀리면 **묻지 말고 바로 이어서** 진행.

**완료(8차, 2026-10-13): 메뉴 글자 깨짐(브라우저 자동 번역) 차단·그래프 보기 점검**
- 사용자 화면: 종합 현황→'비교 현황', 출하시멘트→빈칸, 공정 모니터링→'프로세스 모델링', 원인 진단→'증상의 원인', 강도 예측→'강제 예측', 배합 설계→'설계', 화학 계산기→'화학실험', 보고서→'반대'. 앱 문구가 아니라 **크롬·엣지 자동 번역**(Streamlit 시작 페이지가 `lang="en"`이라 영어로 오인)으로 판단(추정, 유력).
- 조치: `qms/notranslate.py` — 시작 페이지(streamlit/static/index.html)를 `lang="ko" translate="no"` + `<meta name="google" content="notranslate">` 로 고침. 1_SETUP·2_RUN·3_RUN_SHARE 때(`block_translate`)와 앱 시작 때 확인, 앱 화면에서도 보이지 않는 칸에서 한 번 더 지정. 2~6번 ZIP은 그대로(설치 PC에서 고침).
- 상단 메뉴: 간격·글자 약간 줄여 1760px 이상에서 15개 한 줄, 좁으면 영어 'N more' 대신 '더보기'.
- 그래프 보기: 출하시멘트 자료가 없으면 공정 데이터로 시작(빈 화면처럼 보이던 문제), 안내 문구 보강.

**완료(9차, 2026-10-14): 설치 없이 코드로 실행 — `RUN_CODE.bat`**
- 사용자: 코드 다운로드 후 실행 안 됨. 확인된 원인 후보: 저장소 기본 브랜치 `main` 은 처음 만든 OpenAI 채팅 예제뿐(QMS 코드 없음), 파이썬 미설치·사내망 pip 차단.
- `RUN_CODE.bat`(cp949·CRLF, `.gitattributes` 로 변환 금지): 코드 폴더 확인 → 파이썬 찾기(QMS_PY → ..\Blue365_QMS\py → C:\Blue365_QMS\py → py -3 → python) → 3.11 이상·구성요소 확인(없으면 pip) → 127.0.0.1 로 실행. Wine에서 설치 패키지 파이썬 자동 사용·화면 정상 확인.

**완료(10차, 2026-10-15): LIMS DB 간편 연결 — 주소·포트·계정 입력, 비밀번호 암호화, 표 고르기·열 역할·항목 매칭**
- `qms/secret_store.py`: 비밀번호 암호화 저장(Windows DPAPI 현재 사용자 범위 / 그 외 Fernet+data/.secret.key). 값은 다시 보여주지 않음, 다른 PC·계정 값은 빈 값 처리.
- `qms/lims_db.py`: 접속 정보(종류·IP·호스트·포트·DB·아이디·드라이버) → SQLAlchemy URL, 단계별 진단(주소·포트·드라이버·로그인·권한, 한국어 원인 안내), DB·스키마·표/뷰 목록, 미리보기, 열 역할·형식(긴/가로/출하시멘트)·날짜 저장 형식 자동 추천, 시험항목→QMS 항목 추천, 소스별 SELECT(Core, 읽기 전용 세션). MSSQL 비유니코드 문자 열은 NVARCHAR 로 CAST(Windows pymssql 한글 깨짐 대응).
- `qms/lims.py`: 모드 `db`(권장), `LimsConfig.db/sources`, `_sync_db`(소스별 워터마크·실패 격리), `_sync_ship`(출하시멘트 → parse_aoa → shipment.db). 비밀값 우선순위 환경변수 → secrets.toml → 화면 입력(암호화). 데모 LIMS DB에 연습용 뷰 `V_QC_RESULT`.
- `qms/ui_lims.py`·`app_pages/lims.py`: ① 접속 정보(실행 PC에서만 변경)·연결 확인·DB 목록, ② 가져올 곳(표 고르기→형식→열 역할→항목 매칭→미리보기→저장, 이름 중복 방지), REST 토큰 입력.
- `qms/store.py`: 일부 항목만 들어와도(LIMS) 파생값 계산이 멈추지 않게 빈 열 보충(실제 오류 재현 후 수정).
- 검증(사실): Docker 로 띄운 실제 MS SQL Server 2022(Korean_Wansung)·Oracle 23 Free·PostgreSQL 16·MariaDB 11 에서 진단·탐색·매칭·동기화, Wine 에서 Windows용 드라이버(pymssql·oracledb·psycopg2)·DPAPI 확인(pyodbc 는 Wine ODBC 한계로 미확인). 시험 `tests/test_lims_db.py` 7개.
- 설치: 1번 ZIP 이름의 날짜가 바뀌어(v2026.10.15) 새 폴더에 풀리는 경우 대비 — `migrate_data`: 새 설치본 data 가 비어 있으면 주변 이전 설치본 data 를 복사(데모만 있는 설치본·이미 자료가 있는 새 설치본은 건드리지 않음). Wine 재현: 10.13 설치본(출하시멘트·LIMS 설정·DPAPI 비밀번호) → 10.15 새 폴더 설치 → 자료 이전·15화면 정상 → 설치 앱 실행 후 LIMS 화면에서 실제 MSSQL 연결 확인 5단계 통과·동기화 미리보기 25행.

**완료(11차, 2026-10-15): GitHub에서 받아 RUN_CODE.bat 실행 · DB 종류 자동 확인**
- RUN_CODE.bat: 설치한 QMS 파이썬을 코드 폴더 주변·C:\Blue365_QMS·다운로드·바탕화면·문서에서 자동 검색, 설치 앱 데이터 함께 쓰기 선택(data\.run_code_data 기억), 괄호 든 폴더 경로·콘솔 인코딩 문제 수정. 받기 주소: https://github.com/SPC-Blue365/Blue365/archive/refs/heads/ccr-4c0c953d-ll1jyd.zip (저장소 public, 기본 브랜치 main 은 예제뿐).
- `lims_db.detect_type`: 아이디·비밀번호 없이 핸드셰이크로 판별 — MySQL(서버 첫 인사) → MS SQL(TDS PRELOGIN, 버전) → PostgreSQL(SSLRequest) → Oracle(TNS). 화면 '🔎 DB 종류 자동 확인'(DB 종류 자동 변경), 연결 확인에 'DB 종류' 단계. 실제 4종 서버·Windows 파이썬으로 확인.

**완료(12차, 2026-10-15): '가져올 곳' 불러오기 안 됨 대응 · DB 구조를 몰라도 결과 표 자동 찾기**
- 원인 후보(재현): ① 탭 입력을 저장하지 않으면 ② 탭은 예전 접속 정보 사용 / DB 이름을 비우면 MSSQL 기본 DB(master)의 빈 스키마(guest·dbo)만 보임 / ② 탭 '불러오기' 버튼(저장된 설정 열기)을 LIMS 불러오기로 오해.
- 조치: 🩺 연결 확인 성공 시 접속 정보 자동 저장, ② 탭에 사용 중인 접속 표시·미저장 경고, 데이터베이스 선택(MSSQL·PostgreSQL), 혼동 버튼 제거, 소스별 database(여러 DB 지원).
- `lims_db.catalog/explore/score_table/find_term/structure_workbook`: INFORMATION_SCHEMA(MSSQL·PG·MySQL)·ALL_TAB_COLUMNS(Oracle)·sqlite 로 표·열 목록을 한 번에 읽고 날짜·시험항목/결과 열·시험항목 이름 열·출하시멘트 머리글·표 이름으로 점수(잡표 0점), 이름·값 찾기(상위 후보 문자 열 LIKE, 질의 150회 한도), 구조 엑셀. 화면 🧭 자동으로 찾기 → ▶ 이 표로 시작(역할 자동, 긴 형식은 시험항목 목록 자동 불러오기·매칭 추천). 실제 MSSQL(기본 DB=master 재현)·Oracle·PG(여러 DB)·MariaDB, Wine(Windows 드라이버)에서 확인.

**완료(13차, 2026-10-15): 사용자 화면 'No module named pymssql' — DB 드라이버 없는 실행 환경 대응**
- 사용자 캡처: 주소·포트·DB 종류(SQL Server 2022, 10.50.11.71:3718, DB TEST) 정상인데 ② 탭 'DB 목록을 읽지 못했습니다 — No module named pymssql'. 원인: 코드 실행(RUN_CODE)이 PC 파이썬을 썼고 requirements.txt 에 DB 드라이버가 없었음(설치 패키지 파이썬에는 포함). 안내 문구도 'pymssql 로 바꾸라'로 잘못 나옴. 호스트 칸 'MTcyLjE3LjIyLjEx' = Base64 로 인코딩된 172.17.22.11.
- 조치: requirements-lims.txt(드라이버, 비Windows는 cryptography), RUN_CODE.bat 드라이버 하나씩 설치(실패해도 실행 계속)·OneDrive·상위 2단계 검색, `lims_db.driver_ok/install_driver/b64_ip`, 드라이버 선택 상자에 '❌ 이 PC에 없음', ①·② 탭에 '⬇️ 드라이버 설치' 버튼(실행 중인 파이썬에 pip 설치, 사용자 폴더 설치도 바로 인식), No module 안내 정정, Base64 호스트 안내. 드라이버 없는 venv + 실제 MSSQL(포트 3718, DB TEST)로 재현 → 버튼 설치 → 자동 찾기 성공 확인.

**완료(14차, 2026-10-15): 사용자 'TDS server connection failed(20002)' — 로그인 전 TLS 단계 끊김 대응**
- 사용자 서버: SQL Server 2022 RTM(16.0.1000), 10.50.11.71:3718. 드라이버 설치 후 로그인 단계에서 20002(18456 아님 → 비밀번호 문제 아님).
- 재현(사실): 정상 인증서·암호화 강제 서버는 pymssql 정상. 약한 인증서(RSA 1024·SHA1)·TLS 1.0 전용 서버는 pymssql(Windows·Linux) 20017/20002 실패, TDS 7.0 또는 encryption=off 로는 성공(서버가 강제하지 않을 때).
- 조치: `lims_db.connection_plans/try_plan/find_connection/odbc_drivers` — pymssql 기본 → TDS 7.4 → Windows ODBC(SQL Server 드라이버, SChannel) → (동의 시) 암호화 없음·TDS 7.0 순서로 실제 로그인까지 시도, 성공한 설정 저장(conn.tds_version/encryption/driver/odbc_driver, 되돌리기 가능). 아이디·비밀번호·DB 이름 오류면 중단. prelogin 응답의 암호화 설정(필수/강제 아님) 표시, 20002/20017 안내 문구. pyodbc(win32) requirements-lims·RUN_CODE 추가. pyodbc+Windows ODBC 경로는 Wine ODBC 한계로 미확인(실제 Windows 에선 'SQL Server' 드라이버 기본 내장).

**완료(15차, 2026-10-15): 자동 찾기 5가지 방법 모두 20002 실패 → 원인 재현·QMS 보안 중계(TLS relay)·진단 보고서**
- 원인 재현(사실): **암호화 강제 + TLS 1.3 허용** SQL Server 2022 에서 pymssql(Windows 휠·Linux 휠 모두, FreeTDS 1.5.19)은 사용자 화면과 **글자까지 같은** `20002 TDS server connection failed ×2` 로 실패, encryption=off·TDS 7.0 도 실패. FreeTDS 기록: 'handshake succeeded' 직후 'connection dead'(TDS 7.x 에서 TLS 1.3 비호환). Linux SQL Server 이미지는 1024비트·TLS 1.0 설정을 서버 쪽에서 스스로 못 써서 14차의 '약한 인증서 재현'은 서버 자체 한계가 섞여 있었다.
- 버그(사실): Windows ODBC 경로가 DB 이름이 비면 SQLAlchemy 가 IP 를 DSN 이름으로 써서(`dsn=10.50.11.71`) IM002 → 서버에 시도조차 못 함. `lims_db.odbc_string` 으로 연결 문자열 직접 생성(`odbc_connect`, 'SQL Server' 는 Network=DBMSSOCN, 값은 {} 이스케이프).
- 조치: `qms/tds_relay.py`(표준 라이브러리만) — 127.0.0.1 중계가 PRELOGIN 의 ENCRYPTION 을 서버엔 ON·pymssql 엔 NOT_SUP 으로 바꾸고, 서버와 TLS 를 0x12 패킷에 싸서 직접 맺음(프로필 tls12 = TLS 1.2 고정, legacy = TLS 1.0~1.2·SECLEVEL=0). 서버 구간은 계속 암호화(encrypt_option=TRUE 확인). conn.tls_relay 로 저장, `make_engine` 이 자동 적용. 자동 찾기 순서: pymssql → 중계 tls12 → 중계 legacy → Windows ODBC → TDS 7.4 → (동의) 암호화 없음. 로그인 거절(18456)은 TLS 안내보다 먼저 판정.
- 📋 진단 보고서(.txt, `connection_report`): 실행 환경·단계별 확인·PRELOGIN·TLS 버전별 핸드셰이크·서버 인증서(서명 방식·키 길이·만료)·방법별 오류 원문·FreeTDS 기록(TLS·오류 줄만)·자동 판단. 비밀번호 미포함(시험으로 확인).
- 검증: 재현 서버에서 Linux·Wine(Windows 파이썬 3.13·OpenSSL 3.5) 모두 중계로 성공, 브라우저로 연결 확인 실패 → 자동 찾기 성공·저장 → 🧭 표 찾기 → TEST.dbo.QC_RESULT 발견. 가짜 TDS 서버(TLS 1.0·RSA 1024·SHA1)로 legacy 프로필 시험. 테스트 158건.
- 미확인: 사용자 실제 서버(10.50.11.71)의 TLS 설정 — 진단 보고서를 받으면 확정.

**완료(12차, 2026-10-23): LIMS 직접 연동 불가 → 방법 A(폴더 자동 반영) 전환 + 업데이트 양식**
- 사실: LIMS DB 직접 접속 실패 원인 확정 — 사용자가 쓴 'sampyo'는 ftp.ini 의 FTP·웹 로그인 계정이고 DB 로그인 계정이 아님(두 서버 모두 18456). 서버: 10.50.11.71(SQL 2022 RTM), 172.17.22.11(SQL 2014, TLS 1.0·RSA1024 자체서명). 사내망이라 내가 직접 접속 불가. LIMS에 예약 내보내기 기능 없음 → 방법 A 채택.
- `qms/store.py`: `COL_ALIASES`(표별 LIMS·한글 머리글→내부 열), `normalize_product`(품명 '1종시멘트 벌크'→'1종'), `_to_minutes`(응결시간 'HH:MM'→분, TIME_MIN_COLUMNS), `apply_column_aliases`. parse_upload 가 LIMS 엑셀 머리글을 그대로 인식(내부키 템플릿도 하위호환).
- `scripts/build_lims_update_workbook.py` → `docs/Blue365_QMS_업데이트_양식.xlsx`: 한 파일, 시트 사용법·생료·클링커·시멘트·물성·클링커일일·출하시멘트·LIMS매핑. 시멘트·물성·출하시멘트는 사용자 LIMS 샘플 실제값, 생료·클링커·클링커일일은 예시(추정) 표시.
- 검증: parse_upload 오류 0, 5개 공정표 인식, 출하시멘트 70행·17항목 인식. 테스트 160건.
- 다음: 사용자가 양식에 값 채워 지정 폴더에 저장 → 5_MONITOR_TASK(작업 스케줄러)로 매일 자동 반영. 폴더·시각 확정 후 원클릭 스케줄 등록 BAT 정리. (선택) 품질관리 웹 10.62.78.19:3000 의 데이터 출처(F12 Network·설정파일) 확인되면 자동 다운로드 스크립트 검토.

**완료(13차, 2026-10-23): LIMS 원본 내보내기 파일 10종 자동 인식 + 공정별 열 매칭표**
- 사용자 제공 LIMS 샘플 10개 분석. 공정 7종(조합원료 4/5·6/7, 크링커 4/5·수출크링커 6/7, 시멘트공정, 시멘트성적 1종, 3종시멘트성적) + 인수검사 3종(원료·석고·고령토).
- `qms/store.py`: `detect_lims_sheet`(제목 1행+머리글 3행 구조 인식), `LIMS_TITLE_MAP`(조합원료→raw_meal, 크링커/클링커→clinker, 시멘트공정→cement, 시멘트성적→physical), 인수검사류는 무시. `COL_ALIASES`에 용중→clk_lw, 원료온도→cem_mill_temp 등 추가. parse_upload 가 LIMS 원본 파일을 복사·붙여넣기 없이 그대로 인식(엑셀을 header=None 로 읽어 템플릿/LIMS 양쪽 처리). 하위호환 유지.
- `scripts/build_lims_mapping_table.py` → `docs/LIMS_공정별_열매칭표.xlsx`: 요약·상세 매칭·미반영 참고 3시트. HM·SM·LSF·Bogue 는 QMS 자동계산이라 미반영 표시.
- 미매핑 중 의미있는 것: 시멘트공정 완성시멘트 오산화물(QMS 미저장), 조합원료 배합비율(배합설계 입력), 인수검사 전체(표 없음) — 필요 시 표 신설 제안.
- 검증: 7개 공정 파일 parse_upload 오류 0(시멘트공정 465행·조합원료 1532/954행·클링커 294/140행·물성 70/70/16행). 인수검사 3종 정상 무시. 테스트 161건.
- 다음: 사용자 확인 후 자동 반영 폴더·시각 확정→작업 스케줄러 BAT. 인수검사·배합비율 표 신설 여부 결정. 시멘트성적→출하시멘트 중복 반영 정리(현재 physical+shipment 양쪽).

**다음 작업**
1. 사용자 피드백 반영(판정 기준·화면). 사내 관리기준 수치는 사용자가 입력하므로 임의로 채우지 않는다.
2. 선박별 양하지 자료가 오면 선박·양하지 연결(추정 없이 기록된 값만 사용).
3. (선택) 출하시멘트 판정을 알림 센터·종합 현황·원인 진단에 연결, 1·3일 강도로 28일 강도 예측, 보고서(PPT/엑셀) 출력.
4. 패키지를 다시 만들면 `docs/사내망_도입_IT검토요청서.md` 의 해시 갱신.

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
