import os

import streamlit as st

from journal_featured.web import jobs
from journal_featured.web.common import is_running, raw_config

st.title("手動執行")

running = is_running()
raw = raw_config()
recipients = raw.get("recipients") or []
curate_on = (raw.get("curate") or {}).get("enabled", True)

missing = [k for k in ("OPENALEX_API_KEY",) if not os.environ.get(k)]
missing_smtp = [k for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_APP_PASSWORD") if not os.environ.get(k)]
if missing:
    st.warning("尚未設定 OpenAlex API key，請先到「API 與寄信」填寫。", icon=":material/key_off:")
elif missing_smtp:
    st.info("尚未完成 SMTP 設定，目前只能執行不寄信的操作。", icon=":material/mail_lock:")
if running:
    st.info("目前有工作執行中（可能是排程或先前從這裡啟動的），結束前無法再啟動。", icon=":material/hourglass_top:")

days = st.number_input("回溯天數（0 = 使用設定值 "
                       f"{raw.get('lookback_days', 14)} 天）", min_value=0, max_value=365, value=0, step=1)
days_arg = ["--days", str(days)] if days else []
confirm = st.checkbox(f"我確定要寄信給 {len(recipients)} 位收件人：{', '.join(recipients) or '（未設定）'}")

ACTIONS = [
    # key, label, args, sends mail, help
    ("dry", "試跑（dry-run）", ["--dry-run", *days_arg], False,
     "只抓取、評分並印出各議題分數排行，不寫資料庫、不寄信。"
     + ("會呼叫 Claude 精選（約 US$0.1）。" if curate_on else "")),
    ("noemail", "執行，不寄信", ["--no-email", *days_arg], False, "抓取新文章並寫入資料庫，不寄信、不呼叫 Claude。"),
    ("run", "正式執行並寄信", days_arg, True, "與每週排程相同：抓取、評分、Claude 精選、寫資料庫、寄信。"),
    ("curate", "重新精選，不寄信", ["--curate-only", "--no-email"], False,
     "不重新抓取，對最近一次的入選文章重做 Claude 簡評與精選。"),
    ("curate_mail", "重新精選並寄信", ["--curate-only"], True, "同上，完成後寄信。"),
    ("resend", "重寄最近一次", ["--resend"], True, "用資料庫中已存的簡評與精選重寄，不呼叫 Claude。"),
]
cols = st.columns(3)
for i, (key, label, args, mail, help_text) in enumerate(ACTIONS):
    with cols[i % 3]:
        disabled = running or bool(missing) or (mail and (not confirm or bool(missing_smtp)))
        if st.button(label, key=key, help=help_text, disabled=disabled, width="stretch",
                     type="primary" if mail else "secondary"):
            st.session_state["log"] = jobs.start(args, key).name
            st.rerun()
st.caption("寄信類操作需先勾選確認。排程執行的輸出請用 `docker compose logs app` 查看。")

st.subheader("執行輸出")


@st.fragment(run_every=2 if running else None)
def show_log():
    logs = jobs.logs()
    if not logs:
        st.caption("尚無從這裡啟動的執行紀錄。")
        return
    names = [p.name for p in logs]
    current = st.session_state.get("log")
    name = st.selectbox("紀錄", names, index=names.index(current) if current in names else 0)
    text = (jobs.log_dir() / name).read_text(errors="replace")
    code = jobs.exit_code(text)
    if code is None:
        st.info("執行中…", icon=":material/hourglass_top:")
    elif code == 0:
        st.success("完成", icon=":material/check_circle:")
    elif code == 3:
        st.warning("已有另一個工作在執行，本次未啟動", icon=":material/block:")
    else:
        st.error(f"結束代碼 {code}", icon=":material/error:")
    st.code("\n".join(text.splitlines()[-400:]), language=None)
    if running and not is_running():
        st.rerun()  # job finished: refresh the whole page to re-enable the buttons


show_log()
