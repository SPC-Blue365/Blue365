"""사내망 공유 실행 시 선택적 접속 비밀번호(기본 꺼짐).

비밀번호는 환경변수 QMS_ACCESS_PASSWORD 또는 .streamlit/secrets.toml 의 [access] password 에 둔다(git 미포함).
설정하지 않으면 비밀번호 없이 열린다 — 내 PC 전용 실행(localhost)에는 필요 없고,
다른 PC에서 접속하도록 공유할 때 기준·설정 화면을 아무나 바꾸지 못하게 하려면 설정한다.
"""

from __future__ import annotations

import hmac
import os
import tomllib
from pathlib import Path

import streamlit as st

SECRETS_PATH = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
_OK_KEY = "_qms_access_ok"


def access_password() -> str:
    env = os.environ.get("QMS_ACCESS_PASSWORD", "")
    if env:
        return env
    try:
        return str(tomllib.loads(SECRETS_PATH.read_text(encoding="utf-8")).get("access", {}).get("password", ""))
    except (OSError, tomllib.TOMLDecodeError):
        return ""


def check_access() -> bool:
    """비밀번호가 설정돼 있으면 로그인 양식을 보여주고, 통과 전에는 False를 돌려준다."""
    password = access_password()
    if not password or st.session_state.get(_OK_KEY):
        return True
    st.title("🏭 Blue365 QMS")
    with st.form("qms_access"):
        given = st.text_input("접속 비밀번호", type="password")
        submitted = st.form_submit_button("접속")
    if submitted:
        if hmac.compare_digest(given.encode("utf-8"), password.encode("utf-8")):
            st.session_state[_OK_KEY] = True
            st.rerun()
        st.error("비밀번호가 맞지 않습니다.")
    st.caption("비밀번호는 시스템 관리자(품질관리 담당)에게 문의하세요.")
    return False
