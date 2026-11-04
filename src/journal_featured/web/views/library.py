import json
from datetime import date

import pandas as pd
import streamlit as st

from journal_featured.db import _article
from journal_featured.web.common import article_card, bibtex, raw_config, starred, store

st.header("文章庫")

with store() as s:
    df = pd.read_sql("SELECT * FROM articles ORDER BY first_seen DESC, score DESC", s.conn)
if df.empty:
    st.info("資料庫中還沒有文章。")
    st.stop()
stars = starred()

df["matches_list"] = df["matches"].map(lambda m: json.loads(m) if m else [])
df["author_str"] = df["authors"].map(lambda a: ", ".join(json.loads(a or "[]")))
df["topics"] = df["matches_list"].map("、".join)
df["star"] = df["doi"].isin(stars)

c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
query = c1.text_input("關鍵字", placeholder="搜尋標題、摘要、作者（空白分隔，需全部符合）",
                      label_visibility="collapsed")
scope = c2.segmented_control("範圍", ["入選", "收藏", "全部"], default="入選", required=True,
                             label_visibility="collapsed", width="stretch")

published = pd.to_datetime(df["published"], errors="coerce").dt.date
valid = published.dropna()
lo, hi = (valid.min(), valid.max()) if len(valid) else (date.today(), date.today())
topic_options = [t["name"] for t in raw_config().get("topics", [])]
topic_options += sorted(set(df["topic"].dropna()) - set(topic_options) - {""})

# Count the active extra filters (from the previous run's widget state) for the expander label.
active = sum(bool(st.session_state.get(k)) for k in ("f_journals", "f_topics", "f_score"))
period_state = st.session_state.get("f_period")
active += bool(period_state and tuple(period_state) != (lo, hi))
with st.expander("更多篩選" + (f"（已套用 {active} 項）" if active else ""), icon=":material/filter_list:"):
    c3, c4 = st.columns(2)
    journals = c3.multiselect("期刊", sorted(df["journal"].unique()), placeholder="全部", key="f_journals")
    topics = c4.multiselect("主題", topic_options, placeholder="全部", key="f_topics")
    c5, c6 = st.columns(2)
    min_score = c5.slider("最低分數（最高主題分數）", 0.0, 1.0, 0.0, 0.01, key="f_score")
    period = c6.date_input("出版日期", (lo, hi), min_value=lo, max_value=hi, key="f_period")

mask = pd.Series(True, index=df.index)
if scope == "入選":
    mask &= df["selected"] == 1
elif scope == "收藏":
    mask &= df["star"]
if journals:
    mask &= df["journal"].isin(journals)
if topics:
    mask &= df.apply(lambda r: bool(set(topics) & (set(r["matches_list"]) | {r["topic"]})), axis=1)
if min_score:
    mask &= df["score"].fillna(0) >= min_score
if isinstance(period, tuple) and len(period) == 2:
    mask &= published.between(*period) | published.isna()
if query:
    haystack = (df["title"] + " " + df["abstract"].fillna("") + " " + df["author_str"]).str.lower()
    for word in query.lower().split():
        mask &= haystack.str.contains(word, regex=False)
view = df[mask].reset_index(drop=True)

st.caption(f"共 {len(view)} 篇（資料庫 {len(df)} 篇，收藏 {len(stars)} 篇）")
left, right = st.columns([2, 1])
with left:
    event = st.dataframe(
        view[["star", "published", "journal", "title", "topics", "score"]].assign(
            star=view["star"].map({True: "★", False: ""})),
        column_config={
            "star": st.column_config.TextColumn("★", width=40),
            "published": st.column_config.TextColumn("出版日期", width=95),
            "journal": st.column_config.TextColumn("期刊", width=150),
            "title": st.column_config.TextColumn("標題", width="large"),
            "topics": "入選主題", "score": st.column_config.NumberColumn("分數", format="%.3f", width=60),
        },
        hide_index=True, width="stretch", height=min(560, 38 + 35 * max(len(view), 1)), on_select="rerun", selection_mode="single-row",
        key="library_table",
    )
with right:
    rows = [i for i in event.selection.rows if i < len(view)]
    if rows:
        r = view.iloc[rows[0]]
        with st.container(border=True):
            article_card(_article(tuple(r[c] if pd.notna(r[c]) else None for c in (
                "doi", "journal", "title", "published", "authors", "abstract", "url", "topic", "score",
                "selected", "matches", "scores", "note"))), starred=bool(r["star"]), key="library")
    else:
        st.caption("點選左側表格中的一列，可在這裡查看摘要、簡評並加入收藏。")

export = view.drop(columns=["matches_list", "author_str", "matches", "scores", "authors", "star"])
export = export.rename(columns={"topics": "matches"}).assign(authors=view["author_str"], starred=view["star"])
with st.container(horizontal=True):
    st.download_button("下載 CSV", export.to_csv(index=False).encode("utf-8-sig"),
                       "articles.csv", "text/csv", disabled=view.empty, icon=":material/download:")
    st.download_button("下載 BibTeX", bibtex(view.to_dict("records")), "articles.bib",
                       "application/x-bibtex", disabled=view.empty, icon=":material/download:")
