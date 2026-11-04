"""Streamlit entry point: `streamlit run src/journal_featured/web/app.py`."""

from pathlib import Path

import os

import streamlit as st

from journal_featured.config import load_secrets
from journal_featured.web.common import is_running

st.set_page_config(page_title="期刊選讀", page_icon=":material/menu_book:", layout="wide")

# Streamlit's default top padding pushes content a third of the way down the first screen.
st.html("<style>[data-testid='stMainBlockContainer']{padding-top:3rem}</style>")

load_secrets()  # pick up keys saved on the「API 與寄信」page

views = Path(__file__).parent / "views"
secrets_page = st.Page(views / "secrets.py", title="API 與寄信", icon=":material/key:")
page = st.navigation({
    "瀏覽": [
        st.Page(views / "digest.py", title="本週選讀", icon=":material/newspaper:", default=True),
        st.Page(views / "library.py", title="文章庫", icon=":material/library_books:"),
        st.Page(views / "runs.py", title="執行紀錄", icon=":material/history:"),
    ],
    "操作": [
        st.Page(views / "actions.py", title="手動執行", icon=":material/play_circle:"),
        st.Page(views / "settings.py", title="主題與期刊", icon=":material/settings:"),
        st.Page(views / "calibrate.py", title="門檻校準", icon=":material/tune:"),
        secrets_page,
    ],
})
if not os.environ.get("OPENALEX_API_KEY"):
    st.sidebar.warning("尚未設定 OpenAlex API key，無法抓取文章。", icon=":material/key_off:")
    st.sidebar.page_link(secrets_page, label="前往設定", icon=":material/arrow_forward:")
if is_running():
    st.sidebar.info("背景有工作執行中", icon=":material/hourglass_top:")
page.run()
