import os

import streamlit as st
from dotenv import dotenv_values

from journal_featured import fetch, mailer
from journal_featured.config import SECRETS, Smtp, save_secrets
from journal_featured.web.common import raw_config

st.title("API 與寄信")
st.caption("儲存在 data/secrets.env（僅擁有者可讀），會覆蓋 .env 的同名設定。"
           "排程與手動執行下次啟動即使用新值，不需重啟容器。")

if msg := st.session_state.pop("secrets_saved", None):
    st.success(msg, icon=":material/check_circle:")

stored = dotenv_values(SECRETS) if SECRETS.exists() else {}


def source(key: str) -> str:
    return "網頁設定" if stored.get(key) else ".env"


def secret_input(key: str, label: str, help: str | None = None) -> str:
    current = os.environ.get(key, "")
    placeholder = f"已設定（…{current[-4:]}，來源：{source(key)}）；留空則不變更" if current else "未設定"
    return st.text_input(label, type="password", placeholder=placeholder, help=help, key=f"in_{key}")


def plain_input(key: str, label: str, default: str = "", help: str | None = None) -> str:
    return st.text_input(label, os.environ.get(key) or default, help=help, key=f"in_{key}")


with st.form("secrets"):
    st.subheader("OpenAlex（必填）")
    openalex = secret_input("OPENALEX_API_KEY", "OpenAlex API key", "抓取期刊文章用，於 OpenAlex 網站登入後在帳號設定取得")

    st.subheader("Claude 精選（選填）")
    st.caption("未設定則略過精選，其餘流程照常。金鑰在 [Claude Console](https://console.anthropic.com/settings/keys) 建立。")
    anthropic_key = secret_input("ANTHROPIC_API_KEY", "Anthropic API key")
    workspace = plain_input("ANTHROPIC_WORKSPACE_ID", "Workspace ID",
                            help="金鑰未綁定 workspace 時才需要（Console → Settings → Workspaces）")

    st.subheader("寄信（SMTP）")
    st.caption("Gmail 請使用[應用程式密碼](https://myaccount.google.com/apppasswords)，不是登入密碼。")
    c1, c2 = st.columns([3, 1])
    with c1:
        host = plain_input("SMTP_HOST", "主機", "smtp.gmail.com")
    with c2:
        port = plain_input("SMTP_PORT", "埠號", "465", help="465 為 SSL；587 為 STARTTLS")
    user = plain_input("SMTP_USER", "帳號（寄件人）")
    password = secret_input("SMTP_APP_PASSWORD", "應用程式密碼")

    submitted = st.form_submit_button("儲存", type="primary")

if submitted:
    port = port.strip()
    if port and not port.isdigit():
        st.error("埠號需為數字", icon=":material/error:")
    else:
        changes = {k: v.strip() for k, v in {
            "OPENALEX_API_KEY": openalex, "ANTHROPIC_API_KEY": anthropic_key, "SMTP_APP_PASSWORD": password,
        }.items() if v.strip()}  # blank secret = keep the current value
        for k, v in {"ANTHROPIC_WORKSPACE_ID": workspace, "SMTP_HOST": host, "SMTP_PORT": port,
                     "SMTP_USER": user}.items():
            if v.strip() != os.environ.get(k, ""):
                changes[k] = v.strip()
        if changes:
            save_secrets(changes)
            st.session_state["secrets_saved"] = f"已儲存：{', '.join(changes)}"
        else:
            st.session_state["secrets_saved"] = "沒有變更"
        for k in ("OPENALEX_API_KEY", "ANTHROPIC_API_KEY", "SMTP_APP_PASSWORD"):
            st.session_state.pop(f"in_{k}", None)  # don't keep secrets in the inputs
        st.rerun()

st.subheader("測試連線")
st.caption("使用已儲存的設定。")


def smtp_from_env() -> Smtp | None:
    keys = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_APP_PASSWORD")
    if not all(os.environ.get(k) for k in keys):
        return None
    return Smtp(host=os.environ["SMTP_HOST"], port=int(os.environ["SMTP_PORT"]),
                user=os.environ["SMTP_USER"], app_password=os.environ["SMTP_APP_PASSWORD"])


def attempt(label: str, fn) -> None:
    with st.spinner(f"{label}…"):
        try:
            st.success(f"{label}：{fn()}", icon=":material/check_circle:")
        except Exception as e:
            st.error(f"{label}失敗：{type(e).__name__}: {e}", icon=":material/error:")


def test_openalex():
    found = fetch.lookup_issn("Energy Policy", os.environ["OPENALEX_API_KEY"])
    return f"成功（查詢到 {len(found)} 筆期刊）"


def test_claude():
    import anthropic
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)
    model = (raw_config().get("curate") or {}).get("model", "claude-opus-5-5")
    return f"成功（可使用 {client.models.retrieve(model).display_name}）"  # free: no tokens used


def test_smtp():
    mailer.check(smtp_from_env())
    return "登入成功"


def test_mail():
    smtp, to = smtp_from_env(), raw_config().get("recipients") or []
    if not to:
        raise ValueError("設定頁尚未填寫收件人")
    text = "這是期刊選讀的測試信，收到代表寄信設定正確。"
    mailer.send(smtp, to, "期刊選讀：測試信", f"<p>{text}</p>", text)
    return f"已寄出給 {', '.join(to)}"


smtp_ready = smtp_from_env() is not None
c1, c2, c3, c4 = st.columns(4)
if c1.button("測試 OpenAlex", disabled=not os.environ.get("OPENALEX_API_KEY"), width="stretch"):
    attempt("OpenAlex", test_openalex)
if c2.button("測試 Claude", disabled=not os.environ.get("ANTHROPIC_API_KEY"), width="stretch"):
    attempt("Claude", test_claude)
if c3.button("測試 SMTP 登入", disabled=not smtp_ready, width="stretch"):
    attempt("SMTP", test_smtp)
if c4.button("寄測試信", disabled=not smtp_ready, width="stretch"):
    attempt("測試信", test_mail)
