import math
import os

import pandas as pd
import streamlit as st
import yaml

from journal_featured import fetch
from journal_featured.config import ConfigError, save_raw
from journal_featured.web.common import CONFIG, data_dir, raw_config

st.title("議題與期刊")
st.caption("儲存後寫回 config.yaml（保留註解），下次執行即生效；舊版自動備份到 data/config-backups/。")

if msg := st.session_state.pop("saved", None):
    st.success(msg, icon=":material/check_circle:")

raw = raw_config()
backup_dir = data_dir() / "config-backups"


def clean_rows(df: pd.DataFrame, cols: list[str], floats=()) -> list[dict]:
    out = []
    for rec in df.to_dict("records"):
        item = {}
        for c in cols:
            v = rec.get(c)
            if v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip()):
                continue
            item[c] = float(v) if c in floats else str(v).strip()
        if item:
            out.append(item)
    return out


def save(new: dict, label: str) -> None:
    try:
        backup = save_raw(new, CONFIG, backup_dir)
    except ConfigError as e:
        st.error(f"未儲存：{e}", icon=":material/error:")
        return
    st.session_state["saved"] = f"{label}已儲存" + (f"（備份：{backup.name}）" if backup else "")
    st.rerun()


with st.expander("查詢期刊 ISSN", icon=":material/search:"):
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    name = c1.text_input("期刊名稱", key="lookup_name")
    if c2.button("查詢", disabled=not name, width="stretch"):
        try:
            found = fetch.lookup_issn(name, os.environ.get("OPENALEX_API_KEY", ""))
            st.dataframe(pd.DataFrame(found, columns=["名稱", "ISSN"]), hide_index=True, width="stretch")
            st.caption("將 ISSN 複製到下方期刊表格，再按儲存。")
        except Exception as e:
            st.error(f"查詢失敗：{e}")

with st.form("config"):
    st.subheader("議題")
    st.caption("描述宜簡短聚焦（一句話 + 關鍵詞），以英文為佳；門檻留空則使用全域門檻。")
    topics = st.data_editor(
        pd.DataFrame(raw.get("topics") or [], columns=["name", "description", "threshold"]),
        column_config={
            "name": st.column_config.TextColumn("名稱", required=True),
            "description": st.column_config.TextColumn("描述", width="large", required=True),
            "threshold": st.column_config.NumberColumn("門檻", min_value=0.0, max_value=1.0, step=0.005,
                                                       format="%.3f"),
        },
        num_rows="dynamic", hide_index=True, width="stretch", key="topics",
    )

    st.subheader("期刊")
    journals = st.data_editor(
        pd.DataFrame(raw.get("journals") or [], columns=["name", "issn"]),
        column_config={
            "name": st.column_config.TextColumn("名稱", required=True, width="large"),
            "issn": st.column_config.TextColumn("ISSN", help="格式 1234-567X；留空則每次執行時自動查詢"),
        },
        num_rows="dynamic", hide_index=True, width="stretch", key="journals",
    )

    st.subheader("一般")
    c1, c2, c3 = st.columns(3)
    lookback = c1.number_input("回溯天數", 1, 365, int(raw.get("lookback_days", 14)))
    threshold = c2.number_input("全域門檻", 0.0, 1.0, float(raw.get("threshold", 0.85)), 0.005, format="%.3f")
    max_per_topic = c3.number_input("每個議題信中最多篇數", 1, 100, int(raw.get("max_per_topic", 10)))
    send_empty = st.checkbox("沒有入選文章時仍寄信", bool(raw.get("send_empty", True)))
    recipients = st.text_area("收件人（一行一個）", "\n".join(raw.get("recipients") or []))
    model = st.text_input("Embedding 模型", raw.get("model", "intfloat/multilingual-e5-base"),
                          help="更換後第一次執行會下載新模型，且分數分布會改變，需重新校準門檻")

    st.subheader("Claude 精選")
    cur = raw.get("curate") or {}
    c1, c2, c3 = st.columns(3)
    curate_enabled = c1.toggle("啟用", bool(cur.get("enabled", True)))
    picks = c2.number_input("精選篇數", 0, 10, int(cur.get("picks", 2)))
    effort = c3.selectbox("effort", ["low", "medium", "high"],
                          index=["low", "medium", "high"].index(cur.get("effort", "medium")))
    curate_model = st.text_input("模型", cur.get("model", "claude-opus-5-5"))
    interests = st.text_area("關注重點（給 Claude 的說明；留空則使用議題描述）", cur.get("interests", ""), height=160)

    submitted = st.form_submit_button("儲存", type="primary")

if submitted:
    new = dict(raw)
    new["topics"] = clean_rows(topics, ["name", "description", "threshold"], floats={"threshold"})
    new["journals"] = [{**j, "issn": j["issn"].upper()} if "issn" in j else j
                       for j in clean_rows(journals, ["name", "issn"])]
    new["lookback_days"] = int(lookback)
    new["threshold"] = float(threshold)
    new["max_per_topic"] = int(max_per_topic)
    new["send_empty"] = send_empty
    new["recipients"] = [r.strip() for r in recipients.splitlines() if r.strip()]
    new["model"] = model.strip()
    curate = dict(cur, enabled=curate_enabled, picks=int(picks), model=curate_model.strip(), effort=effort)
    if interests.strip():
        curate["interests"] = interests.rstrip() + "\n"
    else:
        curate.pop("interests", None)
    new["curate"] = curate
    save(new, "設定")

backups = sorted(backup_dir.glob("config-*.yaml"), reverse=True) if backup_dir.exists() else []
if backups:
    with st.expander("還原備份", icon=":material/restore:"):
        chosen = st.selectbox("備份", [b.name for b in backups])
        st.code((backup_dir / chosen).read_text(), language="yaml")
        if st.button("還原此版本"):
            save(yaml.safe_load((backup_dir / chosen).read_text()), f"已還原 {chosen}，設定")
