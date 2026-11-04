import json
from datetime import date

import pandas as pd
import streamlit as st

from journal_featured.db import _article
from journal_featured.web.common import article_card, bibtex, raw_config, store

st.title("文章庫")

with store() as s:
    df = pd.read_sql("SELECT * FROM articles ORDER BY first_seen DESC, score DESC", s.conn)
if df.empty:
    st.info("資料庫中還沒有文章。")
    st.stop()

df["matches_list"] = df["matches"].map(lambda m: json.loads(m) if m else [])
df["author_str"] = df["authors"].map(lambda a: ", ".join(json.loads(a or "[]")))
df["topics"] = df["matches_list"].map("、".join)

c1, c2 = st.columns([3, 1])
query = c1.text_input("關鍵字（標題、摘要、作者；空白分隔，需全部符合）")
only_selected = c2.toggle("只看入選", value=True)
c3, c4, c5 = st.columns(3)
journals = c3.multiselect("期刊", sorted(df["journal"].unique()))
topic_options = [t["name"] for t in raw_config().get("topics", [])]
topic_options += sorted(set(df["topic"].dropna()) - set(topic_options) - {""})
topics = c4.multiselect("議題", topic_options)
min_score = c5.slider("最低分數（最高議題分數）", 0.0, 1.0, 0.0, 0.01)

published = pd.to_datetime(df["published"], errors="coerce").dt.date
valid = published.dropna()
lo, hi = (valid.min(), valid.max()) if len(valid) else (date.today(), date.today())
period = st.date_input("出版日期", (lo, hi), min_value=lo, max_value=hi)

mask = pd.Series(True, index=df.index)
if only_selected:
    mask &= df["selected"] == 1
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
view = df[mask]

st.caption(f"共 {len(view)} 篇（資料庫 {len(df)} 篇）")
event = st.dataframe(
    view[["published", "journal", "title", "topics", "score", "selected", "url"]],
    column_config={
        "published": "出版日期", "journal": "期刊", "title": st.column_config.TextColumn("標題", width="large"),
        "topics": "入選議題", "score": st.column_config.NumberColumn("分數", format="%.3f"),
        "selected": st.column_config.CheckboxColumn("入選"),
        "url": st.column_config.LinkColumn("連結", display_text="開啟"),
    },
    hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
)

if rows := event.selection.rows:
    r = view.iloc[rows[0]]
    with st.container(border=True):
        article_card(_article(tuple(r[c] if pd.notna(r[c]) else None for c in (
            "doi", "journal", "title", "published", "authors", "abstract", "url", "topic", "score",
            "selected", "matches", "scores", "note"))))
else:
    st.caption("點選表格中的一列可查看摘要與簡評。")

export = view.drop(columns=["matches_list", "author_str", "matches", "scores", "authors"])
export = export.rename(columns={"topics": "matches"}).assign(authors=view["author_str"])
c1, c2, _ = st.columns([1, 1, 4])
c1.download_button("下載 CSV", export.to_csv(index=False).encode("utf-8-sig"),
                   "articles.csv", "text/csv", disabled=view.empty)
c2.download_button("下載 BibTeX", bibtex(view.to_dict("records")), "articles.bib",
                   "application/x-bibtex", disabled=view.empty)
