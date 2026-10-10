"""Blue365 QMS - Windows 설치·실행 도우미(인터넷 연결 불필요).

배치 파일(1_SETUP.bat 등)이 패키지에 들어 있는 휴대용 Python(py\\python.exe)으로 이 스크립트를 실행한다.
표준 라이브러리만 쓰므로 구성요소(라이브러리)를 설치하기 전에도 동작한다.

  setup [--quick]        최초 설치: 분할 ZIP 결합 → 컴파일 → 구성요소 점검 → 화면 자체 시험(--quick 이면 생략)
  run [--share]          실행(내 PC 전용 / 사내망 공유) — 브라우저 자동 열림
  check                  환경 점검 보고서(logs\\check_*.txt)
  selftest               모든 화면을 임시 데이터로 시험 실행
  task register|unregister|status|run-now [--minutes N]   자동 감시(Windows 작업 스케줄러)
  firewall add|remove|status [--port N]                   방화벽 인바운드 허용(관리자 권한)
  backup                 data 폴더 백업(backups\\QMS_data_*.zip)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import traceback
import urllib.request
import webbrowser
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
PY_DIR = ROOT / "py"
TOOLS = ROOT / "tools"
LOGS = ROOT / "logs"
BACKUPS = ROOT / "backups"
MANIFEST_PATH = TOOLS / "manifest.json"
SETUP_MARK = TOOLS / "setup_ok.json"
TOP = "Blue365_QMS"                     # 분할 ZIP 안의 최상위 폴더명

IS_WIN = os.name == "nt"
TASK_NAME = "Blue365_QMS_Monitor"
FW_PORT_RULE = "Blue365_QMS_TCP{port}"
FW_PROG_RULE = "Blue365_QMS_python"
DEFAULT_PORT = 8501
MAX_PATH = 259                          # Windows 경로 한도 260자(끝 NUL 제외)
TR_LIMIT = 261                          # schtasks /TR 명령 길이 한도
CORE_MODULES = ["streamlit", "pandas", "numpy", "scipy", "plotly", "pyarrow", "openpyxl", "pptx"]
OPTIONAL_MODULES = [("sqlalchemy", "LIMS DB 조회"), ("requests", "LIMS REST API"), ("anthropic", "AI 솔루션 보고서"),
                    ("pyodbc", "MS SQL Server(ODBC)"), ("pymssql", "MS SQL Server"), ("oracledb", "Oracle"),
                    ("psycopg2", "PostgreSQL"), ("pymysql", "MySQL·MariaDB"), ("xlrd", "구형 엑셀(.xls)")]
DIST_NAMES = {"pptx": "python-pptx", "psycopg2": "psycopg2-binary", "pymysql": "PyMySQL", "sqlalchemy": "SQLAlchemy"}
STREAMLIT_BANNER = ("You can now view", "URL:", "server started on", "For better performance", "$ xcode-select",
                    "$ pip install watchdog")


# ───────────────────────────── 공통 ─────────────────────────────
class Report:
    """화면 출력과 보고서 파일 기록을 함께 한다."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, msg: str = "") -> None:
        print(msg, flush=True)
        self.lines.append(msg)

    def save(self, prefix: str) -> Path | None:
        try:
            LOGS.mkdir(parents=True, exist_ok=True)
            path = LOGS / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.txt"
            path.write_text("\r\n".join(self.lines) + "\r\n", encoding="utf-8-sig")
            return path
        except OSError:
            return None


def data_dir() -> Path:
    return Path(os.environ.get("QMS_DATA_DIR") or ROOT / "data")


def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def child_env() -> dict[str, str]:
    """하위 프로세스 환경: 다른 Python 설치의 영향을 막고 데이터 폴더를 패키지 안으로 지정."""
    drop = {"PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUTF8"}
    env = {k: v for k, v in os.environ.items() if k.upper() not in drop}
    env.update(QMS_DATA_DIR=str(data_dir()), PYTHONIOENCODING="utf-8", PYTHONNOUSERSITE="1",
               GIT_PYTHON_REFRESH="quiet", STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    return env


def run_cmd(cmd: list[str], timeout: float = 60) -> tuple[int, str]:
    """Windows 시스템 명령(schtasks·netsh) 실행 - 콘솔 코드 페이지(OEM)로 출력 해석."""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)
    out = (p.stdout or b"") + (p.stderr or b"")
    return p.returncode, out.decode("oem" if IS_WIN else "utf-8", errors="replace").strip()


def secrets() -> dict:
    try:
        return tomllib.loads((APP / ".streamlit" / "secrets.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def access_password_set() -> bool:
    return bool(os.environ.get("QMS_ACCESS_PASSWORD") or secrets().get("access", {}).get("password"))


def dist_version(module: str) -> str:
    from importlib import metadata
    try:
        return metadata.version(DIST_NAMES.get(module, module))
    except metadata.PackageNotFoundError:
        return ""


def page_titles() -> dict[str, str]:
    """streamlit_app.py 의 st.Page 정의에서 화면 파일명 → 한글 제목."""
    try:
        src = (APP / "streamlit_app.py").read_text(encoding="utf-8")
    except OSError:
        return {}
    return dict(re.findall(r'st\.Page\("app_pages/(\w+)\.py",\s*title="([^"]+)"', src))


# ───────────────────────────── 경로·분할 파일 ─────────────────────────────
def long_paths_enabled() -> bool:
    if not IS_WIN:
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


def path_issues(manifest: dict, root: Path | None = None) -> list[tuple[str, str]]:
    """(수준, 메시지) 목록. 수준 'error' 는 설치를 멈춘다."""
    root_s = str(root or ROOT)
    low = root_s.lower()
    out: list[tuple[str, str]] = []
    longest = len(root_s) + 1 + int(manifest.get("max_rel_path", 170))
    if longest > MAX_PATH and not long_paths_enabled():
        out.append(("error", (f"설치 경로가 깁니다({len(root_s)}자). 가장 긴 파일 경로가 {longest}자로 Windows 한도(260자)를 "
                              "넘습니다. Blue365_QMS 폴더를 C:\\Blue365_QMS 처럼 짧은 위치로 옮긴 뒤 다시 실행하세요.")))
    if "\\appdata\\local\\temp\\" in low:          # ZIP 안에서 바로 실행하면 Windows가 여기에 임시로 푼다
        out.append(("warn", "임시 폴더(Temp)에서 실행 중입니다. ZIP 안에서 바로 실행했다면 압축을 모두 푼 뒤 실행하세요."))
    if "onedrive" in low:
        out.append(("warn", "OneDrive 동기화 폴더 안입니다. 파일이 많아 동기화 부하가 생길 수 있으니 C:\\Blue365_QMS 를 권장합니다."))
    return out


def part_installed(part: dict, root: Path | None = None) -> bool:
    """분할 파일 설치 완료 여부 - ZIP의 맨 마지막 항목인 완료 표식이 있고, 표식 내용이 기대값(expect)과 같아야 완료.

    구성요소 ZIP은 구성요소 묶음 식별값(libs), 1번 ZIP은 프로그램 버전으로 확인한다 — 압축 해제가 중간에 끊긴 경우·
    다른 묶음 위에 덮어쓴 경우는 미완료로 보고, 구성요소가 같은 업데이트는 다시 풀지 않는다.
    """
    try:
        mark = json.loads(((root or ROOT) / part["marker"]).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return False
    return all(mark.get(k) == v for k, v in part.get("expect", {}).items())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def search_dirs() -> list[Path]:
    home = Path.home()
    cands = [ROOT, ROOT.parent, ROOT.parent.parent, Path.cwd(), home / "Downloads", home / "Desktop"]
    out: list[Path] = []
    for d in cands:
        try:
            r = d.resolve()
        except OSError:
            continue
        if r not in out and r.is_dir():
            out.append(r)
    return out


def find_part_file(part: dict, dirs: list[Path] | None = None) -> Path | None:
    """분할 ZIP 찾기: 설치 폴더·상위 폴더·다운로드 폴더 순. 브라우저가 '(1)'을 붙인 이름도 크기로 확인."""
    dirs = dirs if dirs is not None else search_dirs()
    name = part["file"]
    for d in dirs:
        if (d / name).is_file():
            return d / name
    stem = Path(name).stem
    for d in dirs:
        for p in sorted(d.glob(f"{stem}*.zip")):
            if p.is_file() and p.stat().st_size == part.get("size"):
                return p
    return None


def extract_part(zpath: Path, say=print, root: Path | None = None) -> int:
    """분할 ZIP을 설치 폴더에 푼다(ZIP 안 'Blue365_QMS/' 아래만, 폴더 밖으로 나가는 경로는 무시)."""
    root = (root or ROOT).resolve()
    prefix = TOP + "/"
    written = 0
    with zipfile.ZipFile(zpath) as z:
        infos = [i for i in z.infolist() if not i.is_dir() and i.filename.startswith(prefix)]
        step = max(1, len(infos) // 10)
        for n, info in enumerate(infos, 1):
            target = (root / info.filename[len(prefix):]).resolve()
            if root not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            written += 1
            if n % step == 0 or n == len(infos):
                say(f"      {n * 100 // len(infos):3d}%  ({n:,}/{len(infos):,}개 파일)")
    return written


def setup_done() -> bool:
    try:
        mark = json.loads(SETUP_MARK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    man = load_manifest()
    return mark.get("version") == man.get("version") and all(part_installed(p) for p in man.get("parts", []))


# ───────────────────────────── 점검 ─────────────────────────────
_IMPORT_PROBE = """
import importlib, json, sys
res = {}
for m in sys.argv[1:]:
    try:
        importlib.import_module(m)
        res[m] = ""
    except Exception as exc:
        res[m] = f"{type(exc).__name__}: {exc}"[:300]
print(json.dumps(res))
"""


def import_check(say) -> bool:
    mods = CORE_MODULES + [m for m, _ in OPTIONAL_MODULES]
    try:
        p = subprocess.run([sys.executable, "-s", "-c", _IMPORT_PROBE, *mods], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=child_env(), timeout=900, check=False)
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
        say(f"  [오류] 구성요소 점검을 실행하지 못했습니다: {exc}")
        return False
    ok = True
    for m in CORE_MODULES:
        err = res.get(m, "점검 안 됨")
        ok &= not err
        say(f"  {'정상' if not err else '오류'}  {m:<11} {dist_version(m):<9} {err}")
    for m, label in OPTIONAL_MODULES:
        err = res.get(m, "점검 안 됨")
        say(f"  {'정상' if not err else '없음'}  {m:<11} {dist_version(m):<9} {label}{' - 선택 기능, ' + err if err else ''}")
    return ok


def compile_all() -> int:
    """설치 PC에서 1회 컴파일(.pyc) - 이후 실행 속도 향상. 실패한 파일이 있어도 실행에는 영향 없음."""
    cmd = [sys.executable, "-E", "-s", "-m", "compileall", "-q", "-j", "0", str(PY_DIR / "Lib")]
    try:
        return subprocess.run(cmd, capture_output=True, env=child_env(), timeout=1800, check=False).returncode
    except (OSError, subprocess.TimeoutExpired):
        return -1


def run_tee(cmd: list[str], say, env: dict | None = None, cwd: Path | None = None) -> int:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", env=env, cwd=cwd)
    for line in proc.stdout:
        say(line.rstrip())
    return proc.wait()


def local_ipv4() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:  # 기본 경로의 IP(실제 패킷은 보내지 않음)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.", "0.")))


_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def health_ok(port: int) -> bool:
    try:
        with _NO_PROXY.open(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as r:
            return r.status == 200 and r.read(16).strip() == b"ok"
    except Exception:  # noqa: BLE001 - 응답 없음·거부·시간 초과 모두 '아님'
        return False


def port_status(port: int) -> str:
    """'free'(비어 있음) · 'qms'(QMS 실행 중) · 'other'(다른 프로그램 사용 중)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            pass
    except OSError:
        return "free"
    return "qms" if health_ok(port) else "other"


def is_admin() -> bool:
    if not IS_WIN:
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def is_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, delete=True):
            pass
        return True
    except OSError:
        return False


# ───────────────────────────── setup ─────────────────────────────
def cmd_setup(args) -> int:
    say = Report()
    man = load_manifest()
    say(f"[Blue365 QMS 설치]  패키지 {man.get('version', '?')} · Python {platform.python_version()}")
    say(f"  설치 위치: {ROOT}")
    issues = path_issues(man)
    for level, msg in issues:
        say(f"  [{'중단' if level == 'error' else '주의'}] {msg}")
    if any(level == "error" for level, _ in issues):
        say.save("setup")
        return 2
    if port_status(DEFAULT_PORT) == "qms":           # 실행 중이면 사용 중인 파일을 덮어쓸 수 없음
        say("  [중단] Blue365 QMS가 실행 중입니다. 실행 창(2_RUN·3_RUN_SHARE)을 닫은 뒤 다시 실행하세요.")
        say.save("setup")
        return 2

    core = {"marker": man.get("core_marker", ""), "expect": man.get("core_expect", {})}
    if man.get("core_marker") and not part_installed(core):
        say(f"  [중단] {man.get('core_file', '1번 ZIP')} 의 압축 해제가 끝나지 않았습니다. 같은 위치에 다시 압축을 푸세요(덮어쓰기).")
        say.save("setup")
        return 2
    parts = man.get("parts", [])
    say()
    say(f"1단계: 구성요소 파일 확인 (분할 파일 {len(parts)}개)")
    missing = []
    for part in parts:
        if part_installed(part):
            say(f"  - {part['file']}: 이미 설치됨")
            continue
        z = find_part_file(part)
        if z is None:
            say(f"  - {part['file']}: 파일을 찾을 수 없음")
            missing.append(part["file"])
            continue
        say(f"  - {part['file']}: 무결성(SHA-256) 확인 중…")
        if sha256_file(z) != part["sha256"]:
            say(f"    [오류] 파일이 손상되었거나 일부만 전송되었습니다: {z}")
            missing.append(part["file"])
            continue
        say("    압축 해제 중…")
        extract_part(z, say)
        if not part_installed(part):
            say("    [오류] 압축을 풀었지만 일부 파일이 없습니다(보안 프로그램 차단 여부 확인).")
            missing.append(part["file"])
    if missing:
        say()
        say("  [중단] 아래 파일이 필요합니다. 받은 ZIP 파일을 이 폴더에 복사한 뒤 1_SETUP.bat 을 다시 실행하세요.")
        for m in missing:
            say(f"     · {m}")
        say(f"     복사할 위치: {ROOT}")
        say.save("setup")
        return 3

    say()
    say("2단계: 실행 준비 - 파이썬 파일 컴파일(1회, 1~5분 소요)…")
    t0 = time.time()
    rc = compile_all()
    say(f"  완료({time.time() - t0:.0f}초){'' if rc == 0 else ' - 일부 파일은 건너뜀(실행에는 영향 없음)'}")

    say()
    say("3단계: 구성요소 점검")
    if not import_check(say):
        say("  [중단] 필수 구성요소를 불러오지 못했습니다. 9_CHECK.bat 결과(logs 폴더)를 담당자에게 전달하세요.")
        say.save("setup")
        return 4

    if not getattr(args, "quick", False):
        say()
        say("4단계: 화면 자체 시험(임시 데이터 사용, 1~5분 소요)")
        rc = run_tee([sys.executable, "-s", str(Path(__file__).resolve()), "selftest"], say, env=child_env())
        if rc != 0:
            say("  [주의] 일부 화면에서 오류가 났습니다. 프로그램은 실행되지만 해당 화면은 확인이 필요합니다.")

    for d in (data_dir(), LOGS):
        d.mkdir(parents=True, exist_ok=True)
    if not is_writable(data_dir()):
        say(f"  [주의] 데이터 폴더에 쓸 수 없습니다: {data_dir()} - 쓰기 가능한 위치로 옮기세요.")
    SETUP_MARK.write_text(json.dumps({"version": man.get("version"), "at": f"{datetime.now():%Y-%m-%d %H:%M}",
                                      "python": platform.python_version()}, ensure_ascii=False), encoding="utf-8")
    say()
    say("설치가 끝났습니다.")
    say("  · 내 PC에서 보기       : 2_RUN.bat")
    say("  · 사내망 공유(다른 PC) : 3_RUN_SHARE.bat  (처음 1회 4_FIREWALL_ADMIN.bat - 관리자 권한)")
    say("  · 자동 감시·알림 등록  : 5_MONITOR_TASK.bat")
    path = say.save("setup")
    if path:
        say(f"  설치 기록: {path}")
    return 0


# ───────────────────────────── selftest ─────────────────────────────
def cmd_selftest(args) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="qms_selftest_"))
    os.environ["QMS_DATA_DIR"] = str(tmp)            # 실제 data 폴더는 건드리지 않음
    sys.path.insert(0, str(APP))
    os.chdir(APP)
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # noqa: BLE001
        print(f"  [오류] Streamlit 시험 모듈을 불러오지 못했습니다: {exc}")
        return 1
    titles = page_titles()
    pages = sorted(p.stem for p in (APP / "app_pages").glob("*.py") if not p.stem.startswith("_"))
    fails: list[tuple[str, list[str]]] = []
    t0 = time.time()
    at = AppTest.from_file(str(APP / "streamlit_app.py"), default_timeout=900)
    at.session_state["_qms_access_ok"] = True        # 접속 비밀번호를 설정해 둔 경우에도 시험
    try:
        at.run()
        err = [str(e.value) for e in at.exception]
    except Exception as exc:  # noqa: BLE001
        err = [f"{type(exc).__name__}: {exc}"]
    print(f"  시험용 데모 데이터 생성·첫 화면: {'정상' if not err else '오류'} ({time.time() - t0:.0f}초)", flush=True)
    if err:
        fails.append(("첫 화면", err))
    for i, page in enumerate(pages, 1):
        t = time.time()
        try:
            at.switch_page(f"app_pages/{page}.py")
            at.run()
            err = [str(e.value) for e in at.exception]
        except Exception as exc:  # noqa: BLE001
            err = [f"{type(exc).__name__}: {exc}"]
        print(f"  [{i:2d}/{len(pages)}] {titles.get(page, page)}: {'정상' if not err else '오류'} ({time.time() - t:.1f}초)",
              flush=True)
        if err:
            fails.append((titles.get(page, page), err))
    shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        for name, errs in fails:
            print(f"  [오류] {name}: {' / '.join(e[:300] for e in errs)}")
        return 1
    print(f"  모든 화면 정상({len(pages)}개, 총 {time.time() - t0:.0f}초)")
    return 0


# ───────────────────────────── run ─────────────────────────────
def _pump(proc: subprocess.Popen, log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} 서버 시작 =====\n")
        for line in proc.stdout:
            log.write(line)
            log.flush()
            if not any(s in line for s in STREAMLIT_BANNER) and line.strip():
                print(line.rstrip(), flush=True)


def streamlit_cmd(port: int, share: bool) -> list[str]:
    return [sys.executable, "-s", "-m", "streamlit", "run", "streamlit_app.py",
            "--server.port", str(port), "--server.address", "0.0.0.0" if share else "127.0.0.1",
            "--server.headless", "true", "--server.fileWatcherType", "none", "--server.runOnSave", "false",
            "--browser.gatherUsageStats", "false"]


def cmd_run(args) -> int:
    if not setup_done():
        print("처음 실행이라 설치(구성요소 결합·점검)를 먼저 진행합니다.\n")
        rc = cmd_setup(argparse.Namespace(quick=True))
        if rc:
            return rc
        print()
    port = args.port
    status = port_status(port)
    if status == "qms":
        print(f"QMS가 이미 실행 중입니다 → http://localhost:{port}")
        if args.share:
            print("공유 모드로 다시 시작하려면 실행 중인 QMS 창을 먼저 닫은 뒤 3_RUN_SHARE.bat 을 실행하세요.")
        if not args.no_browser:
            webbrowser.open(f"http://localhost:{port}", new=2)
        time.sleep(3)
        return 0
    if status == "other":
        new = next((p for p in range(port + 1, port + 20) if port_status(p) == "free"), None)
        if new is None:
            print(f"[오류] 포트 {port}~{port + 19}를 모두 다른 프로그램이 쓰고 있습니다.")
            return 1
        print(f"포트 {port}를 다른 프로그램이 쓰고 있어 {new}번으로 실행합니다.")
        port = new

    LOGS.mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"server_{datetime.now():%Y%m%d}.log"
    print("Blue365 QMS를 시작하는 중입니다(보통 10~40초)…", flush=True)
    proc = subprocess.Popen(streamlit_cmd(port, args.share), cwd=APP, env=child_env(), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    threading.Thread(target=_pump, args=(proc, log_path), daemon=True).start()
    t0 = time.time()
    while not health_ok(port):
        if proc.poll() is not None or time.time() - t0 > 240:
            print(f"[오류] 시작하지 못했습니다. 기록 파일을 확인하세요: {log_path}")
            if proc.poll() is None:
                proc.terminate()
            return 1
        time.sleep(0.5)

    url = f"http://localhost:{port}"
    line = "=" * 64
    print(f"\n{line}\n Blue365 QMS 실행 중 {'(사내망 공유)' if args.share else '(내 PC 전용)'}")
    print(f"   이 PC에서 보기   : {url}")
    if args.share:
        ips = local_ipv4()
        for i, ip in enumerate(ips):
            print(f"   {'다른 PC에서 접속 :' if i == 0 else ' ' * 18} http://{ip}:{port}")
        print(f"   {'다른 PC에서 접속 :' if not ips else ' ' * 18} http://{socket.gethostname()}:{port}")
        if ips:
            print(f"   태블릿·휴대폰    : http://{ips[0]}:{port}/?view=tablet  (QR 코드: 프로그램 왼쪽 메뉴 맨 아래)")
        print(f"   접속 비밀번호    : {'설정됨' if access_password_set() else '미설정 - 사내망 누구나 접속·설정 변경 가능(README 6항)'}")
        print("   접속이 안 되면   : 4_FIREWALL_ADMIN.bat(관리자) 실행 또는 IT에 TCP 인바운드 허용 요청")
    print(f"   종료             : 이 창을 닫거나 Ctrl+C\n{line}\n", flush=True)
    if not args.no_browser:
        webbrowser.open(url, new=2)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        try:
            return proc.wait(timeout=15)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            proc.terminate()
            return 0


# ───────────────────────────── check ─────────────────────────────
def cmd_check(args) -> int:
    say = Report()
    man = load_manifest()
    say(f"[Blue365 QMS 환경 점검]  {datetime.now():%Y-%m-%d %H:%M}")
    say(f"  패키지     : {man.get('version', '?')} (빌드 {man.get('built_at', '?')}, git {man.get('git_commit', '?')})")
    say(f"  Python     : {platform.python_version()} ({sys.executable})")
    say(f"  Windows    : {platform.platform()} · 컴퓨터 이름 {socket.gethostname()}")
    say(f"  설치 위치  : {ROOT} ({len(str(ROOT))}자)")
    for level, msg in path_issues(man):
        say(f"    [{'문제' if level == 'error' else '주의'}] {msg}")
    d = data_dir()
    try:
        free = f"{shutil.disk_usage(ROOT).free / 1e9:.1f} GB"
    except OSError:
        free = "확인 불가"
    say(f"  데이터 폴더: {d} ({'쓰기 가능' if is_writable(d) else '쓰기 불가'}, 디스크 여유 {free})")
    try:
        mark = json.loads(SETUP_MARK.read_text(encoding="utf-8"))
        say(f"  설치 상태  : 완료({mark.get('at')}){'' if setup_done() else ' - 단, 버전이 바뀌어 1_SETUP.bat 재실행 필요'}")
    except (OSError, ValueError):
        say("  설치 상태  : 미완료 - 1_SETUP.bat 을 실행하세요")
    missing = [p["file"] for p in man.get("parts", []) if not part_installed(p)]
    if missing:
        say(f"  분할 파일  : 미설치 {', '.join(missing)}")
    say("  구성요소:")
    ok = import_check(say)
    st = port_status(DEFAULT_PORT)
    say(f"  포트 {DEFAULT_PORT}  : {({'free': '사용 가능', 'qms': 'QMS 실행 중', 'other': '다른 프로그램이 사용 중'})[st]}")
    say(f"  IP 주소    : {', '.join(local_ipv4()) or '확인 불가'}")
    if IS_WIN:
        rc, _ = run_cmd(["netsh", "advfirewall", "firewall", "show", "rule", f"name={FW_PORT_RULE.format(port=DEFAULT_PORT)}"])
        say(f"  방화벽 규칙: {'있음' if rc == 0 else '없음(사내망 공유 시 4_FIREWALL_ADMIN.bat)'}")
        rc, _ = run_cmd(["schtasks", "/Query", "/TN", TASK_NAME])
        say(f"  자동 감시  : {'등록됨' if rc == 0 else '미등록'}")
    sec = secrets()
    lims_on = False
    try:
        lims_on = bool(json.loads((d / "lims.json").read_text(encoding="utf-8")).get("enabled"))
    except (OSError, ValueError):
        pass
    ai_key = bool(os.environ.get("ANTHROPIC_API_KEY") or sec.get("anthropic", {}).get("api_key"))
    say(f"  설정       : secrets.toml {'있음' if sec else '없음'} · 접속 비밀번호 {'설정됨' if access_password_set() else '미설정'}"
        f" · LIMS 연동 {'켜짐' if lims_on else '꺼짐'} · AI 키 {'설정됨' if ai_key else '미설정'}")
    proxy = [k for k in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY") if os.environ.get(k) or os.environ.get(k.lower())]
    say(f"  프록시 변수: {', '.join(proxy) if proxy else '없음'}")
    path = say.save("check")
    say(f"\n점검 결과 저장: {path}" if path else "")
    return 0 if ok else 1


# ───────────────────────────── task ─────────────────────────────
def task_command() -> str:
    return f'"{PY_DIR / "pythonw.exe"}" -E -s "{TOOLS / "monitor_task.pyw"}"'


def cmd_task(args) -> int:
    if args.action == "run-now":
        print("자동 감시를 지금 1회 실행합니다(LIMS 동기화 → 이상 감지 → 알림).\n", flush=True)
        return subprocess.call([sys.executable, "-s", str(TOOLS / "monitor_task.pyw"), "--console"], env=child_env())
    if not IS_WIN:
        print("Windows 작업 스케줄러 전용 기능입니다.")
        return 1
    if args.action == "register":
        if not 5 <= args.minutes <= 1439:
            print("실행 간격은 5~1439분 사이로 지정하세요.")
            return 1
        tr = task_command()
        if len(tr) > TR_LIMIT:
            print(f"[오류] 설치 경로가 길어 작업을 등록할 수 없습니다({len(tr)}자 > {TR_LIMIT}자). C:\\Blue365_QMS 처럼 짧은 위치로 옮기세요.")
            return 1
        rc, out = run_cmd(["schtasks", "/Create", "/TN", TASK_NAME, "/TR", tr, "/SC", "MINUTE", "/MO", str(args.minutes), "/F"])
        print(out)
        if rc == 0:
            print(f"\n등록 완료: {args.minutes}분마다 실행됩니다(이 PC에 로그인해 있는 동안). 실행 기록: {LOGS / 'monitor.log'}")
            print("알림 발송 대상·채널은 프로그램의 [기준·알림 설정] 화면에서 정합니다.")
        else:
            print("\n[실패] 회사 보안 정책으로 작업 스케줄러 사용이 막혀 있으면 IT 담당자에게 문의하세요.")
        return rc
    if args.action == "unregister":
        rc, out = run_cmd(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        print(out if rc == 0 else "등록된 자동 감시 작업이 없습니다.")
        return 0
    rc, out = run_cmd(["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"])
    print(out if rc == 0 else "자동 감시 작업이 등록되어 있지 않습니다.")
    log = LOGS / "monitor.log"
    if log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        print("\n[최근 실행 기록]\n" + "\n".join(tail))
    return 0


# ───────────────────────────── firewall ─────────────────────────────
def firewall_cmds(action: str, port: int) -> list[list[str]]:
    py = str(PY_DIR / "python.exe")
    base = ["netsh", "advfirewall", "firewall"]
    port_rule = FW_PORT_RULE.format(port=port)
    remove = [base + ["delete", "rule", "name=all", f"program={py}"],   # 경고창 '취소'로 생긴 차단 규칙 포함
              base + ["delete", "rule", f"name={port_rule}"]]
    if action == "remove":
        return remove
    if action == "add":
        return remove + [
            base + ["add", "rule", f"name={port_rule}", "dir=in", "action=allow", "protocol=TCP", f"localport={port}",
                    "profile=domain,private"],
            base + ["add", "rule", f"name={FW_PROG_RULE}", "dir=in", "action=allow", f"program={py}", "enable=yes",
                    "profile=domain,private"],
        ]
    return [base + ["show", "rule", f"name={port_rule}"], base + ["show", "rule", f"name={FW_PROG_RULE}"]]


def cmd_firewall(args) -> int:
    if not IS_WIN:
        print("Windows 방화벽 전용 기능입니다.")
        return 1
    if args.action != "status" and not is_admin():
        port_rule = FW_PORT_RULE.format(port=args.port)
        print("[안내] 방화벽 설정은 관리자 권한이 필요합니다.")
        print("  방법 1) 4_FIREWALL_ADMIN.bat 을 마우스 오른쪽 버튼으로 클릭 → '관리자 권한으로 실행'")
        print("  방법 2) 관리자 계정이 없으면 IT 담당자에게 아래 내용을 요청하세요.")
        print(f"     - 인바운드 허용: TCP {args.port} (도메인·개인 프로필)")
        print(f"     - 프로그램: {PY_DIR / 'python.exe'}")
        print(f"     - 명령 예: netsh advfirewall firewall add rule name={port_rule} dir=in action=allow protocol=TCP "
              f"localport={args.port} profile=domain,private")
        return 1
    failed = False
    for cmd in firewall_cmds(args.action, args.port):
        rc, out = run_cmd(cmd)
        if cmd[3] in ("add", "show"):           # delete 는 규칙이 없을 때도 실패로 끝나므로 결과를 보지 않음
            print(out)
            failed |= rc != 0
    if args.action == "add":
        print("\n" + ("방화벽 허용을 등록했습니다. 3_RUN_SHARE.bat 으로 실행한 뒤 다른 PC에서 접속해 보세요." if not failed
                      else "일부 규칙 등록에 실패했습니다. 회사 정책(GPO)으로 막혀 있으면 IT에 요청하세요."))
    elif args.action == "remove":
        print("Blue365 QMS 방화벽 규칙을 삭제했습니다.")
    return int(failed and args.action == "add")


# ───────────────────────────── backup ─────────────────────────────
def cmd_backup(args) -> int:
    d = data_dir()
    files = [p for p in d.rglob("*") if p.is_file() and not p.name.endswith(("-wal", "-shm", "-journal"))] \
        if d.is_dir() else []
    if not files:
        print("백업할 데이터가 없습니다.")
        return 0
    BACKUPS.mkdir(parents=True, exist_ok=True)
    out = BACKUPS / f"QMS_data_{datetime.now():%Y%m%d_%H%M%S}.zip"
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            arc = (Path("data") / p.relative_to(d)).as_posix()
            if p.suffix.lower() == ".db":           # 실행 중에도 일관된 사본(SQLite 백업 API)
                snap = Path(tmp) / f"{len(z.namelist())}_{p.name}"
                with closing(sqlite3.connect(p)) as src, closing(sqlite3.connect(snap)) as dst:
                    src.backup(dst)
                z.write(snap, arc)
            else:
                z.write(p, arc)
    print(f"백업 완료: {out}  ({out.stat().st_size / 1e6:.1f} MB, 파일 {len(files)}개)")
    print("복원: 프로그램 창을 닫고, 이 ZIP 안의 data 폴더를 Blue365_QMS 폴더에 덮어쓰면 됩니다.")
    print("※ 접속 비밀번호·메일·LIMS 비밀번호(app\\.streamlit\\secrets.toml)는 백업에 넣지 않습니다(따로 보관).")
    return 0


# ───────────────────────────── main ─────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="qms_launcher", description="Blue365 QMS Windows 설치·실행 도우미")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="최초 설치")
    s.add_argument("--quick", action="store_true", help="화면 자체 시험 생략")
    r = sub.add_parser("run", help="실행")
    r.add_argument("--share", action="store_true", help="사내망 공유(다른 PC 접속 허용)")
    r.add_argument("--port", type=int, default=DEFAULT_PORT)
    r.add_argument("--no-browser", action="store_true", help="브라우저 자동 열기 안 함")
    sub.add_parser("check", help="환경 점검")
    sub.add_parser("selftest", help="화면 자체 시험")
    sub.add_parser("backup", help="데이터 백업")
    t = sub.add_parser("task", help="자동 감시(작업 스케줄러)")
    t.add_argument("action", choices=["register", "unregister", "status", "run-now"])
    t.add_argument("--minutes", type=int, default=30)
    f = sub.add_parser("firewall", help="방화벽 허용(관리자)")
    f.add_argument("action", choices=["add", "remove", "status"])
    f.add_argument("--port", type=int, default=DEFAULT_PORT)
    return ap


HANDLERS = {"setup": cmd_setup, "run": cmd_run, "check": cmd_check, "selftest": cmd_selftest, "task": cmd_task,
            "firewall": cmd_firewall, "backup": cmd_backup}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return int(HANDLERS[args.cmd](args) or 0)
    except KeyboardInterrupt:
        return 130
    except Exception:  # noqa: BLE001 - 현장 PC에서 원인 파악용 기록을 남긴다
        detail = traceback.format_exc()
        print(detail)
        try:
            LOGS.mkdir(parents=True, exist_ok=True)
            path = LOGS / f"error_{datetime.now():%Y%m%d_%H%M%S}.txt"
            path.write_text(detail, encoding="utf-8")
            print(f"예기치 않은 오류입니다. 이 파일을 담당자에게 전달하세요: {path}")
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
