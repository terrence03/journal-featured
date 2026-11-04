import base64

import streamlit as st

from journal_featured import mailer, score
from journal_featured.config import Topic
from journal_featured.web.common import article_card, md, raw_config, store

st.title("本週選讀")

with store() as s:
    runs = s.runs()
    if not runs:
        st.info("尚無執行紀錄。可到「手動執行」頁跑第一次。")
        st.stop()
    labels = {r["id"]: f"{r['until']}（{r['since']} ~ {r['until']}）· 入選 {r['selected']} 篇" for r in runs}
    run_id = st.selectbox("期別", list(labels), format_func=labels.get)
    run = next(r for r in runs if r["id"] == run_id)
    articles = s.run_articles(run_id)
    featured = s.featured(run_id, articles)

c1, c2, c3, c4 = st.columns(4)
c1.metric("新文章", run["new_count"])
c2.metric("入選", run["selected"])
c3.metric("寄送", run["mail_status"])
c4.metric("執行時間", run["run_at"])
if run["errors"]:
    with st.expander("本次執行有錯誤", icon=":material/warning:"):
        st.code(run["errors"], language=None)

raw = raw_config()
names = [t["name"] for t in raw.get("topics", [])]
names += sorted({m for a in articles for m in a.matches} - set(names))  # topics removed since
topics = [Topic(name=n, description="") for n in names]

if featured:
    st.subheader("Claude 精選")
    for a, reason in featured:
        with st.container(border=True):
            article_card(a)
            st.markdown(f"**推薦理由**　{md(reason)}")

groups = score.pick(articles, topics, max_per_topic=10**6)
if not groups:
    st.info("本期沒有符合議題的新文章。")
tabs = st.tabs([f"{t}（{len(v)}）" for t, v in groups.items()] + ["信件預覽"])
for tab, (topic, items) in zip(tabs, groups.items()):
    with tab:
        for a in items:
            with st.container(border=True):
                article_card(a, topic)
with tabs[-1]:
    mail_groups = score.pick(articles, topics, int(raw.get("max_per_topic", 10)))
    html, _ = mailer.render(mail_groups, run["since"], run["until"], featured)
    # data: URL keeps the email (external titles/notes) in an opaque origin, isolated from the app.
    st.iframe("data:text/html;charset=utf-8;base64," + base64.b64encode(html.encode()).decode(), height=900)
