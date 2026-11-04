import os

import streamlit as st

from journal_featured.web import jobs
from journal_featured.web.common import is_running, raw_config

st.header("手動執行")

running = is_running()
raw = raw_config()
recipients = raw.get("recipients") or []
curate_on = (raw.get("curate") or {}).get("enabled", True)
default_days = int(raw.get("lookback_days", 14))

missing = not os.environ.get("OPENALEX_API_KEY")
missing_smtp = [k for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_APP_PASSWORD") if not os.environ.get(k)]
if missing:
    st.warning("尚未設定 OpenAlex API key，請先到「API 與寄信」填寫。", icon=":material/key_off:")
elif missing_smtp:
    st.info("尚未完成 SMTP 設定，目前只能執行不寄信的操作。", icon=":material/mail_lock:")
if running:
    st.info("目前有工作執行中（可能是排程或先前從這裡啟動的），結束前無法再啟動。", icon=":material/hourglass_top:")


def launch(args: list[str], key: str) -> None:
    st.session_state["log"] = jobs.start(args, key).name
    st.rerun()


@st.dialog("確認寄信")
def confirm(label: str, args: list[str], key: str) -> None:
    st.write(f"「{label}」會寄信給 {len(recipients)} 位收件人：")
    st.markdown("\n".join(f"- {r}" for r in recipients))
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("取消"):
            st.rerun()
        if st.button("確認寄出", type="primary", icon=":material/send:"):
            launch(args, key)


def action(key: str, label: str, args: list[str], mail: bool, *, primary: bool = False, icon=None) -> None:
    disabled = running or missing or (mail and (bool(missing_smtp) or not recipients))
    if st.button(label, key=key, disabled=disabled, type="primary" if primary else "secondary", icon=icon):
        if mail:
            confirm(label, args, key)
        else:
            launch(args, key)


with st.container(border=True):
    days = st.number_input("回溯天數", min_value=1, max_value=365, value=default_days, step=1,
                           help=f"設定值為 {default_days} 天；只影響這次執行（試跑、正式執行、執行不寄信）", width=220)
    days_arg = ["--days", str(days)] if days != default_days else []
    with st.container(horizontal=True):
        action("run", "正式執行並寄信", days_arg, True, primary=True, icon=":material/send:")
        action("dry", "試跑（dry-run）", ["--dry-run", *days_arg], False, icon=":material/science:")
    st.caption("正式執行與每週排程相同：抓取、評分、Claude 精選、寫資料庫、寄信。"
               "試跑只印出各主題分數排行，不寫資料庫、不寄信"
               + ("，但會呼叫 Claude 精選（約 US$0.1）。" if curate_on else "。"))

with st.expander("其他操作", icon=":material/more_horiz:"):
    OTHERS = [
        ("noemail", "執行，不寄信", ["--no-email", *days_arg], False, "抓取新文章並寫入資料庫，不寄信、不呼叫 Claude。"),
        ("curate", "重新精選，不寄信", ["--curate-only", "--no-email"], False,
         "不重新抓取，對最近一次的入選文章重做 Claude 簡評與精選。"),
        ("curate_mail", "重新精選並寄信", ["--curate-only"], True, "同上，完成後寄信。"),
        ("resend", "重寄最近一次", ["--resend"], True, "用資料庫中已存的簡評與精選重寄，不呼叫 Claude。"),
    ]
    for key, label, args, mail, help_text in OTHERS:
        c1, c2 = st.columns([1, 3], vertical_alignment="center")
        with c1:
            action(key, label, args, mail)
        c2.caption(help_text)

st.subheader("執行輸出")


@st.fragment(run_every=2 if running else None)
def show_log():
    logs = jobs.logs()
    if not logs:
        st.caption("尚無執行紀錄。從這裡或排程啟動的執行，輸出都會列在這裡。")
        return
    names = [p.name for p in logs]
    current = st.session_state.get("log")
    by_name = {p.name: p for p in logs}
    name = st.selectbox("紀錄", names, index=names.index(current) if current in names else 0,
                        format_func=lambda n: jobs.describe(by_name[n]))
    text = by_name[name].read_text(errors="replace")
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
