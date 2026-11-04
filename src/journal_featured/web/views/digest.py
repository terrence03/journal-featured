import base64
from datetime import datetime

import streamlit as st

from journal_featured import mailer, score
from journal_featured.config import Topic
from journal_featured.schedule import DEFAULT, next_run
from journal_featured.web.common import article_card, md, raw_config, starred, store

WEEKDAYS = "一二三四五六日"

raw = raw_config()

with store() as s:
    runs = s.runs()
    if not runs:
        st.header("本週選讀")
        st.info("尚無執行紀錄。可到「手動執行」頁跑第一次。")
        st.stop()
    labels = {r["id"]: f"{r['until']}（{r['since']} ~ {r['until']}）· 入選 {r['selected']} 篇" for r in runs}
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    with c1:
        st.header("本週選讀")
    run_id = c2.selectbox("期別", list(labels), format_func=labels.get, label_visibility="collapsed")
    run = next(r for r in runs if r["id"] == run_id)
    articles = s.run_articles(run_id)
    featured = s.featured(run_id, articles)
stars = starred()


@st.dialog("信件預覽", width="large")
def preview(groups, featured):
    html, _ = mailer.render(groups, run["since"], run["until"], featured)
    # data: URL keeps the email (external titles/notes) in an opaque origin, isolated from the app.
    st.iframe("data:text/html;charset=utf-8;base64," + base64.b64encode(html.encode()).decode(), height=700)


summary = [f"{run['new_count']} 篇新文章", f"入選 {run['selected']}", run["mail_status"], f"執行於 {run['run_at']}"]
try:
    nxt = next_run(" ".join(str(raw.get("schedule") or DEFAULT).split()), datetime.now().astimezone())
except ValueError:
    nxt = None
if nxt:
    summary.append(f"下次排程 {nxt:%m/%d}（{WEEKDAYS[nxt.weekday()]}）{nxt:%H:%M}")
c1, c2 = st.columns([5, 1], vertical_alignment="center")
c1.caption(" · ".join(summary))

names = [t["name"] for t in raw.get("topics", [])]
names += sorted({m for a in articles for m in a.matches} - set(names))  # topics removed since
topics = [Topic(name=n, description="") for n in names]
if c2.button("信件預覽", icon=":material/mail:", width="stretch"):
    preview(score.pick(articles, topics, int(raw.get("max_per_topic", 10))), featured)

if run["errors"]:
    with st.expander("本次執行有錯誤", icon=":material/warning:"):
        st.code(run["errors"], language=None)

if featured:
    st.subheader("Claude 精選")
    for a, reason in featured:
        with st.container(border=True):
            article_card(a, starred=a.doi in stars, key="featured")
            st.markdown(f"**推薦理由**　{md(reason)}")

groups = score.pick(articles, topics, max_per_topic=10**6)
if not groups:
    st.info("本期沒有符合主題的新文章。")
    st.stop()
st.subheader("依主題")
for tab, (topic, items) in zip(st.tabs([f"{t}（{len(v)}）" for t, v in groups.items()]), groups.items()):
    with tab:
        for a in items:
            with st.container(border=True):
                article_card(a, topic, starred=a.doi in stars, key=topic)
