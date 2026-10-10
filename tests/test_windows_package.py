"""사내망 Windows 설치 패키지: 설치 도우미(qms_launcher)·자동 감시 실행기·빌드 스크립트의 플랫폼 독립 부분 시험."""

import importlib.util
import json
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WIN = REPO / "packaging" / "windows"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = _load("qms_launcher", WIN / "launcher" / "qms_launcher.py")
B = _load("build_windows_package", REPO / "scripts" / "build_windows_package.py")


@pytest.fixture()
def fake_root(tmp_path, monkeypatch):
    """설치 폴더 구조를 임시 폴더에 만들고 도우미의 경로 상수를 그쪽으로 돌린다."""
    root = tmp_path / "Blue365_QMS"
    (root / "tools").mkdir(parents=True)
    paths = {"ROOT": root, "APP": root / "app", "PY_DIR": root / "py", "TOOLS": root / "tools", "LOGS": root / "logs",
             "BACKUPS": root / "backups", "MANIFEST_PATH": root / "tools" / "manifest.json",
             "SETUP_MARK": root / "tools" / "setup_ok.json"}
    for k, v in paths.items():
        monkeypatch.setattr(L, k, v)
    monkeypatch.delenv("QMS_DATA_DIR", raising=False)        # conftest 의 임시 데이터 폴더 대신 설치 폴더\data
    return root


def _part_zip(path: Path, libs: str, files: list[tuple[str, str]]) -> dict:
    with zipfile.ZipFile(path, "w") as z:
        for arc, data in files:
            z.writestr(arc, data)
        z.writestr("Blue365_QMS/tools/parts/2of2.done", json.dumps({"libs": libs}))
    return {"file": path.name, "marker": "tools/parts/2of2.done", "size": path.stat().st_size, "expect": {"libs": libs}}


def test_extract_part_writes_inside_root_only_and_checks_marker(fake_root, tmp_path):
    zp = tmp_path / "Blue365_QMS_win64_libs-aaaa_2of2.zip"
    part = _part_zip(zp, "aaaa", [("Blue365_QMS/py/Lib/site-packages/foo/__init__.py", "x = 1"),
                                  ("Blue365_QMS/../evil.txt", "bad"), ("other/evil2.txt", "bad")])
    assert not L.part_installed(part)
    assert L.extract_part(zp, say=lambda m: None) == 2
    assert (fake_root / "py/Lib/site-packages/foo/__init__.py").read_text() == "x = 1"
    assert not (tmp_path / "evil.txt").exists() and not (fake_root / "other").exists()   # 폴더 밖 경로 무시
    assert L.part_installed(part)
    assert not L.part_installed({**part, "expect": {"libs": "bbbb"}})   # 다른 구성요소 묶음이면 다시 결합


def test_find_part_file_handles_browser_renamed_download(tmp_path):
    d = tmp_path / "dl"
    d.mkdir()
    renamed = d / "Blue365_QMS_win64_vX_2of3 (1).zip"
    renamed.write_bytes(b"abc")
    part = {"file": "Blue365_QMS_win64_vX_2of3.zip", "size": 3}
    assert L.find_part_file(part, [d]) == renamed
    assert L.find_part_file({**part, "size": 4}, [d]) is None   # 크기가 다르면 다른 파일


def test_path_issues_flags_long_install_path(monkeypatch):
    monkeypatch.setattr(L, "long_paths_enabled", lambda: False)
    man = {"max_rel_path": 161}
    assert any(level == "error" for level, _ in L.path_issues(man, Path("C:/" + "x" * 120)))
    assert not [m for level, m in L.path_issues(man, Path("C:/Blue365_QMS")) if level == "error"]
    assert any("OneDrive" in m for _, m in L.path_issues(man, Path("C:/Users/a/OneDrive/Blue365_QMS")))
    zip_view = "C:\\Users\\a\\AppData\\Local\\Temp\\Temp1_x.zip\\Blue365_QMS"   # ZIP 안에서 바로 실행한 경우
    assert any("Temp" in m for _, m in L.path_issues(man, Path(zip_view)))
    assert not L.path_issues(man, Path("C:\\Temp\\Blue365_QMS"))                   # 사용자가 정한 C:\Temp 는 정상


def test_setup_done_requires_matching_versions(fake_root):
    (fake_root / "tools/parts").mkdir()
    (fake_root / "tools/manifest.json").write_text(json.dumps(
        {"version": "v2", "parts": [{"file": "p2.zip", "marker": "tools/parts/2of2.done", "expect": {"libs": "L1"}}]}))
    (fake_root / "tools/parts/2of2.done").write_text(json.dumps({"libs": "L1"}))
    (fake_root / "tools/setup_ok.json").write_text(json.dumps({"version": "v1"}))
    assert not L.setup_done()                         # 새 버전으로 바뀌면 설치 점검을 다시 한다
    (fake_root / "tools/setup_ok.json").write_text(json.dumps({"version": "v2"}))
    assert L.setup_done()
    (fake_root / "tools/parts/2of2.done").unlink()
    assert not L.setup_done()


def test_firewall_and_scheduled_task_commands(fake_root):
    py = str(fake_root / "py" / "python.exe")
    add = L.firewall_cmds("add", 8501)
    assert ["netsh", "advfirewall", "firewall", "delete", "rule", "name=all", f"program={py}"] in add   # 차단 규칙 정리
    assert any({"localport=8501", "protocol=TCP", "action=allow", "dir=in"} <= set(c) for c in add)
    assert all(c[3] == "delete" for c in L.firewall_cmds("remove", 8501))
    tr = L.task_command()
    assert tr.count('"') == 4 and "pythonw.exe" in tr and " -E -s " in tr and tr.endswith('monitor_task.pyw"')
    assert len(tr) <= L.TR_LIMIT


def test_backup_takes_consistent_sqlite_snapshot(fake_root):
    data = fake_root / "data"
    data.mkdir()
    with closing(sqlite3.connect(data / "qms.db")) as con:
        con.execute("create table t(x)")
        con.execute("insert into t values (42)")
        con.commit()
    (data / "settings.json").write_text("{}")
    assert L.cmd_backup(None) == 0
    (zp,) = list((fake_root / "backups").glob("QMS_data_*.zip"))
    with zipfile.ZipFile(zp) as z:
        assert set(z.namelist()) == {"data/qms.db", "data/settings.json"}
        z.extract("data/qms.db", fake_root / "restore")
    with closing(sqlite3.connect(fake_root / "restore/data/qms.db")) as con:
        assert con.execute("select x from t").fetchone() == (42,)


def test_page_titles_match_navigation(monkeypatch):
    monkeypatch.setattr(L, "APP", REPO)
    titles = L.page_titles()
    pages = [p for p in (REPO / "app_pages").glob("*.py") if not p.stem.startswith("_")]
    assert titles["overview"] == "종합 현황" and len(titles) == len(pages)


def test_monitor_task_wrapper_logs_and_passes_arguments(tmp_path):
    root = tmp_path / "Blue365_QMS"
    (root / "tools").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "tools" / "monitor_task.pyw").write_bytes((WIN / "launcher" / "monitor_task.pyw").read_bytes())
    (root / "app" / "qms_monitor.py").write_text(
        "import os\ndef main(argv):\n    print('인자', argv, os.environ['QMS_DATA_DIR'].endswith('data'))\n    return 3\n",
        encoding="utf-8")
    env = {"PATH": "", "SYSTEMROOT": "", "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([sys.executable, str(root / "tools" / "monitor_task.pyw"), "--console", "--dry-run"],
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=60, check=False)
    assert p.returncode == 3
    log = (root / "logs" / "monitor.log").read_text(encoding="utf-8")
    assert "자동 감시 시작" in log and "인자 ['--dry-run'] True" in log and "종료(코드 3)" in log
    assert "인자 ['--dry-run'] True" in p.stdout                     # --console: 창에도 표시
    subprocess.run([sys.executable, str(root / "tools" / "monitor_task.pyw")], env=env, timeout=60, check=False)
    assert "인자 ['--sync-lims', '--since-hours', '24']" in (root / "logs" / "monitor.log").read_text(encoding="utf-8")


def test_bat_templates_cp949_guarded_and_safe_echo():
    bats = sorted((WIN / "bat").glob("*.bat"))
    assert [b.name[0] for b in bats] == list("1234569")
    for bat in bats:
        text = bat.read_text(encoding="utf-8")
        text.encode("cp949")                                          # 한글 Windows 기본 코드 페이지로 저장 가능
        assert 'cd /d "%~dp0"' in text and "goto nopy" in text and ":nopy" in text
        assert '-E -s "%~dp0tools\\qms_launcher.py"' in text
        for line in text.splitlines():
            if line.lower().startswith("echo"):
                assert not any(ch in line for ch in "&|<>^%"), line  # cmd 특수문자 금지


def test_build_helpers_encoding_and_packing():
    assert B.to_bat("@echo off\necho 설치\n") == "@echo off\r\necho 설치\r\n".encode("cp949")
    txt = B.to_txt("가\n나\n")
    assert txt.startswith(b"\xef\xbb\xbf") and txt.count(b"\r\n") == 2
    sizes = {"a": 60, "b": 50, "c": 40, "d": 30}
    bins = B.pack(sizes, 95)
    assert max(sum(sizes[k] for k in b) for b in bins) <= 95
    assert sorted(k for b in bins for k in b) == sorted(sizes)


def test_app_files_exclude_dev_files_and_secrets():
    files = B.app_files()
    assert {"streamlit_app.py", "qms/access.py", ".streamlit/config.toml", ".streamlit/secrets.toml.example"} <= set(files)
    assert not [f for f in files if f.startswith(("tests/", "scripts/", "packaging/", "data/", "docs/src/"))]
    assert not [f for f in files if f.endswith("secrets.toml")]


def test_library_zips_are_reproducible(tmp_path):
    """같은 내용이면 파일 시각이 달라도 같은 ZIP(같은 SHA-256) — 구성요소가 그대로인 업데이트는 1번 파일만 전달."""
    import os
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("print(1)\n")
    (src / "b.dll").write_bytes(bytes(range(256)) * 50)
    (src / "m.done").write_text('{"libs": "x"}')
    entries = [(src / "b.dll", "Blue365_QMS/py/b.dll"), (src / "a.py", "Blue365_QMS/py/a.py")]
    B.write_zip(tmp_path / "1.zip", entries, (src / "m.done", "Blue365_QMS/tools/parts/2of2.done"))
    os.utime(src / "a.py", (1_000_000_000, 1_000_000_000))                 # 시각만 바꿈
    B.write_zip(tmp_path / "2.zip", list(reversed(entries)), (src / "m.done", "Blue365_QMS/tools/parts/2of2.done"))
    assert B.sha256(tmp_path / "1.zip") == B.sha256(tmp_path / "2.zip")
    with zipfile.ZipFile(tmp_path / "1.zip") as z:
        assert z.namelist()[-1] == "Blue365_QMS/tools/parts/2of2.done"     # 완료 표식은 맨 마지막
    assert B.libs_id(entries, 28_000_000) == B.libs_id(list(reversed(entries)), 28_000_000)
    assert B.libs_id(entries, 28_000_000) != B.libs_id(entries, 95_000_000)  # 분할 한도가 다르면 다른 묶음
