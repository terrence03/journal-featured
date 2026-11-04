import math
import os
from datetime import datetime, time

import pandas as pd
import streamlit as st
import yaml

from journal_featured import fetch
from journal_featured.schedule import CRON, DEFAULT, describe, next_run
from journal_featured.web.common import backup_dir, raw_config, save_config, show_saved

st.header("主題與期刊")
st.caption("各分頁分別儲存，寫回 config.yaml（保留註解），下次執行即生效；舊版自動備份，可在「進階」還原。")
show_saved()

raw = raw_config()
WEEKDAYS = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 0: "日"}


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


def parse_schedule(expr: str) -> tuple[str, list[int], time]:
    """('每天' | '每週' | '自訂', weekdays, time) for the schedule picker."""
    parts = expr.split()
    if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit() and parts[2:4] == ["*", "*"] \
            and int(parts[0]) < 60 and int(parts[1]) < 24:
        at = time(int(parts[1]), int(parts[0]))
        if parts[4] == "*":
            return "每天", [1], at
        days = parts[4].split(",")
        if all(d.isdigit() and int(d) <= 7 for d in days):
            return "每週", sorted({int(d) % 7 for d in days}, key=lambda d: (d == 0, d)), at
    return "自訂", [1], time(8, 0)


t_topics, t_journals, t_schedule, t_claude, t_advanced = st.tabs(
    ["主題", "期刊", "排程與寄信", "Claude 精選", "進階"])

with t_topics:
    with st.form("topics_form", border=False):
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
        threshold = st.number_input("全域門檻", 0.0, 1.0, float(raw.get("threshold", 0.85)), 0.005, format="%.3f",
                                    help="主題沒有自己的門檻時使用")
        if st.form_submit_button("儲存主題", type="primary"):
            save_config({"topics": clean_rows(topics, ["name", "description", "threshold"], floats={"threshold"}),
                         "threshold": float(threshold)}, "主題")
    st.page_link("views/calibrate.py", label="不確定門檻要設多少？到「門檻校準」看分數分布",
                 icon=":material/tune:")

with t_journals:
    journals_now = raw.get("journals") or []
    have = {str(j.get("issn") or "").upper() for j in journals_now}
    with st.container(border=True):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        name = c1.text_input("查詢期刊 ISSN", placeholder="輸入期刊名稱，例：Energy Policy", key="lookup_name")
        if c2.button("查詢", disabled=not name, width="stretch", icon=":material/search:"):
            try:
                st.session_state["lookup"] = fetch.lookup_issn(name, os.environ.get("OPENALEX_API_KEY", ""))
            except Exception as e:
                st.session_state.pop("lookup", None)
                st.error(f"查詢失敗：{e}")
        found = st.session_state.get("lookup")
        if found == []:
            st.caption("查無結果。")
        for i, (jname, issn) in enumerate(found or []):
            c1, c2, c3 = st.columns([4, 1, 1], vertical_alignment="center")
            c1.write(jname)
            c2.write(issn or "（無 ISSN）")
            added = bool(issn) and issn.upper() in have
            if c3.button("已在清單" if added else "加入", key=f"add-{i}", disabled=added or not issn,
                         width="stretch"):
                st.session_state.pop("journals", None)  # reset the editor to the saved list
                save_config({"journals": [*journals_now, {"name": jname, "issn": issn.upper()}]},
                            f"「{jname}」")

    with st.form("journals_form", border=False):
        journals = st.data_editor(
            pd.DataFrame(journals_now, columns=["name", "issn"]),
            column_config={
                "name": st.column_config.TextColumn("名稱", required=True, width="large"),
                "issn": st.column_config.TextColumn("ISSN", help="格式 1234-567X；留空則每次執行時自動查詢"),
            },
            num_rows="dynamic", hide_index=True, width="stretch", key="journals",
        )
        if st.form_submit_button("儲存期刊", type="primary"):
            save_config({"journals": [{**j, "issn": j["issn"].upper()} if "issn" in j else j
                                      for j in clean_rows(journals, ["name", "issn"])]}, "期刊")

with t_schedule:
    current = " ".join(str(raw.get("schedule") or DEFAULT).split())
    freq0, days0, at0 = parse_schedule(current)
    freq = st.segmented_control("頻率", ["每天", "每週", "自訂"], default=freq0, required=True)
    if freq == "自訂":
        expr = st.text_input("cron", current,
                             help="分 時 日 月 星期，依容器時區。例：30 7 1 * * = 每月 1 日 07:30")
    else:
        c1, c2 = st.columns([3, 1])
        days = [1]
        if freq == "每週":
            days = c1.pills("星期", list(WEEKDAYS), default=days0, selection_mode="multi",
                            format_func=WEEKDAYS.get) or []
        at = c2.time_input("時間", at0, step=300)
        dow = ",".join(str(d) for d in days) if freq == "每週" else "*"
        expr = f"{at.minute} {at.hour} * * {dow}" if dow else ""
    expr = " ".join(expr.split())
    if not expr:
        st.caption("請至少選一天。")
    elif not CRON.match(expr):
        st.caption("格式錯誤：需為 5 欄 cron。")
    else:
        try:
            nxt = next_run(expr, datetime.now().astimezone())
            st.caption(f"{describe(expr)}　·　下次：{nxt:%Y-%m-%d %H:%M}" if nxt else describe(expr))
        except ValueError as e:
            st.caption(f"格式錯誤：{e}")

    c1, c2 = st.columns(2)
    lookback = c1.number_input("回溯天數", 1, 365, int(raw.get("lookback_days", 14)),
                               help="每週跑但回溯較長，以涵蓋延遲上架的文章；已看過的文章不會重複")
    max_per_topic = c2.number_input("每個主題信中最多篇數", 1, 100, int(raw.get("max_per_topic", 10)))
    recipients = st.text_area("收件人（一行一個）", "\n".join(raw.get("recipients") or []))
    send_empty = st.checkbox("沒有入選文章時仍寄信", bool(raw.get("send_empty", True)))
    if st.button("儲存排程與寄信", type="primary", disabled=not expr):
        save_config({"schedule": expr, "lookback_days": int(lookback), "max_per_topic": int(max_per_topic),
                     "recipients": [r.strip() for r in recipients.splitlines() if r.strip()],
                     "send_empty": send_empty}, "排程與寄信")
    st.caption("排程儲存後約 30 秒內生效，不需重啟。")

with t_claude:
    cur = raw.get("curate") or {}
    with st.form("curate_form", border=False):
        c1, c2, c3 = st.columns(3, vertical_alignment="bottom")
        curate_enabled = c1.toggle("啟用 Claude 精選", bool(cur.get("enabled", True)))
        picks = c2.number_input("精選篇數", 0, 10, int(cur.get("picks", 2)))
        effort = c3.selectbox("思考深度（effort）", ["low", "medium", "high"],
                              index=["low", "medium", "high"].index(cur.get("effort", "medium")))
        interests = st.text_area("關注重點（給 Claude 的說明，一行一點；留空則使用主題描述）",
                                 cur.get("interests", ""), height=180)
        with st.expander("模型"):
            curate_model = st.text_input("Claude 模型", cur.get("model", "claude-opus-5-5"))
        if st.form_submit_button("儲存 Claude 精選", type="primary"):
            curate = dict(cur, enabled=curate_enabled, picks=int(picks), model=curate_model.strip(), effort=effort)
            if interests.strip():
                curate["interests"] = interests.rstrip() + "\n"
            else:
                curate.pop("interests", None)
            save_config({"curate": curate}, "Claude 精選")

with t_advanced:
    with st.form("model_form", border=False):
        model = st.text_input("Embedding 模型", raw.get("model", "intfloat/multilingual-e5-base"),
                              help="更換後第一次執行會下載新模型，且分數分布會改變，需重新校準門檻")
        if st.form_submit_button("儲存模型"):
            save_config({"model": model.strip()}, "Embedding 模型")

    st.divider()
    backups = sorted(backup_dir().glob("config-*.yaml"), reverse=True) if backup_dir().exists() else []
    st.markdown("**還原備份**")
    if not backups:
        st.caption("尚無備份。")
    else:
        chosen = st.selectbox("備份", [b.name for b in backups], label_visibility="collapsed")
        with st.expander("檢視內容"):
            st.code((backup_dir() / chosen).read_text(), language="yaml")
        if st.button("還原此版本", icon=":material/restore:"):
            save_config(yaml.safe_load((backup_dir() / chosen).read_text()), f"已還原 {chosen}，設定", replace=True)
