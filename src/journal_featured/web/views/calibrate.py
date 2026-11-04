"""Threshold calibration: per-topic score distribution from every article seen so far."""

import json

import altair as alt
import pandas as pd
import streamlit as st

from journal_featured.web import jobs
from journal_featured.web.common import (is_running, raw_config, save_config, show_saved, starred, store,
                                         topic_threshold)

st.header("門檻校準")
st.caption("用資料庫中所有看過的文章，檢視每個主題的分數分布，試調門檻後套用。"
           "門檻只影響之後的執行；分數是當時依主題描述算出的，若改過描述，舊分數僅供參考。")
show_saved()

raw = raw_config()
names = [t["name"] for t in raw.get("topics") or []]
if not names:
    st.info("尚未設定主題。")
    st.stop()

with store() as s:
    df = pd.read_sql("SELECT doi, title, journal, url, topic, matches, scores, run_id, first_seen FROM articles",
                     s.conn)
stars = starred()
no_scores = int(df["scores"].isna().sum())
df = df.dropna(subset=["scores"])


def job_active() -> bool:
    """The lock is held, or the rescore started from here hasn't written its exit line yet."""
    if is_running():
        return True
    log = st.session_state.get("rescore_log")
    if log and (jobs.log_dir() / log).exists():
        return jobs.exit_code((jobs.log_dir() / log).read_text(errors="replace")) is None
    return False


running = job_active()


@st.fragment(run_every=3)
def wait_for_job():
    if not job_active():
        st.rerun()


def rescore_panel(prompt: str) -> None:
    """Recompute every article's per-topic scores with the current topic descriptions (background job)."""
    if running:
        st.info("背景工作執行中，完成後此頁會自動更新。進度可在「手動執行」頁查看。", icon=":material/hourglass_top:")
        wait_for_job()
        return
    with st.container(horizontal=True, vertical_alignment="center"):
        if st.button("重新計算分數", icon=":material/refresh:", disabled=not len(df) + no_scores):
            st.session_state["rescore_log"] = jobs.start(["--rescore"], "rescore").name
            st.rerun()
        st.caption(prompt)


if df.empty:
    st.info("資料庫中的文章都是在記錄各主題分數之前評分的，需要先重新計算一次。", icon=":material/info:")
    rescore_panel("以目前的主題描述與模型重新計算所有文章分數，約需 1 分鐘，不改變各期入選紀錄。")
    st.stop()

topic = st.segmented_control("主題", names, default=names[0], required=True)
current = topic_threshold(raw, topic)

df["score"] = df["scores"].map(lambda s: json.loads(s).get(topic))
missing = int(df["score"].isna().sum())
df = df.dropna(subset=["score"]).reset_index(drop=True)
if df.empty:
    st.info("這個主題是在所有文章評分之後才新增的，還沒有分數資料。")
    st.stop()
# Starred articles count for this topic only if they belonged to it (matched it, or it was their best topic).
df["star"] = df["doi"].isin(stars) & df.apply(
    lambda r: r["topic"] == topic or topic in json.loads(r["matches"] or "[]"), axis=1)

lo, hi = float(df["score"].min()), float(df["score"].max())
lo, hi = min(lo, current) - 0.005, max(hi, current) + 0.005
new = st.slider("試調門檻", round(lo, 3), round(hi, 3), round(current, 3), 0.001, format="%.3f",
                key=f"t-{topic}")

n_runs = max(df["run_id"].nunique(), 1)
cur_n, new_n = int((df["score"] >= current).sum()), int((df["score"] >= new).sum())
starred_below = df[df["star"] & (df["score"] < new)]
c1, c2, c3 = st.columns(3)
c1.metric("目前門檻", f"{current:.3f}", f"入選 {cur_n} 篇", delta_color="off", delta_arrow="off")
c2.metric("試調門檻", f"{new:.3f}", f"入選 {new_n} 篇（{new_n - cur_n:+d}）", delta_color="off",
          delta_arrow="off")
c3.metric("平均每期入選", f"{new_n / n_runs:.1f} 篇", f"共 {n_runs} 期、{len(df)} 篇", delta_color="off",
          delta_arrow="off")

dark = st.context.theme.type == "dark"
ink = "#f0efec" if dark else "#0b0b0b"
selected_color, other_color, star_color = ("#3987e5", "#5f5e5a", "#d95926") if dark else \
    ("#2a78d6", "#c3c2bb", "#eb6834")

df["狀態"] = df["score"].map(lambda v: "入選" if v >= new else "未入選")
kinds = ["入選", "未入選", "★ 收藏"]
color = alt.Color("狀態:N", scale=alt.Scale(domain=kinds, range=[selected_color, other_color, star_color]),
                  legend=alt.Legend(orient="top", title=None))
x_scale = alt.Scale(domain=[lo, hi], nice=False)
ticks = [round(v / 100, 2) for v in range(int(lo * 100) + 1, int(hi * 100) + 1)]  # every 0.01
x_axis = alt.Axis(values=ticks, format=".2f", labelOverlap=True)
peak = int(df.groupby((df["score"] / 0.005).astype(int)).size().max())
hist = alt.Chart(df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
    x=alt.X("score:Q", bin=alt.Bin(step=0.005, extent=[round(lo, 3), round(hi, 3)]), title="相似度", scale=x_scale,
            axis=x_axis),
    # headroom above the tallest bar keeps the starred-article row at the top clear of the bars
    y=alt.Y("count():Q", title="文章數", scale=alt.Scale(domain=[0, peak * 1.25 + 1])),
    color=color,
    tooltip=[alt.Tooltip("score:Q", bin=alt.Bin(step=0.005), title="分數區間", format=".3f"),
             alt.Tooltip("count():Q", title="文章數"), alt.Tooltip("狀態:N")],
)
rules = alt.Chart(pd.DataFrame({"t": [current, new], "門檻": ["目前", "試調"]})).mark_rule(
    color=ink, strokeWidth=2).encode(
    x=alt.X("t:Q", scale=x_scale),
    strokeDash=alt.StrokeDash("門檻:N", scale=alt.Scale(domain=["目前", "試調"], range=[[4, 4], [1, 0]]),
                              legend=alt.Legend(orient="top")),
    tooltip=[alt.Tooltip("門檻:N"), alt.Tooltip("t:Q", title="值", format=".3f")],
)
layers = [hist, rules]
if df["star"].any():
    layers.append(alt.Chart(df[df["star"]].assign(狀態="★ 收藏")).mark_point(
        filled=True, size=90, opacity=1, stroke="white" if not dark else "#1a1a19", strokeWidth=2).encode(
        x=alt.X("score:Q", scale=x_scale), y=alt.value(10), color=color,
        tooltip=[alt.Tooltip("title:N", title="★ 收藏"), alt.Tooltip("score:Q", title="分數", format=".3f")],
    ))
st.altair_chart(alt.layer(*layers).properties(height=300), width="stretch")

if missing or no_scores:
    st.caption(f"另有 {missing + no_scores} 篇文章沒有此主題的分數，未列入；重新計算分數即可補上。")
if len(starred_below):
    st.warning(f"收藏的文章中有 {len(starred_below)} 篇低於試調門檻，之後同類文章可能會被排除。",
               icon=":material/star:")

changed = new != round(current, 3)
with st.container(horizontal=True, vertical_alignment="center"):
    if st.button(f"套用 {new:.3f} 到「{topic}」", type="primary", disabled=not changed):
        topics = [dict(t, threshold=float(new)) if t.get("name") == topic else t for t in raw["topics"]]
        save_config({"topics": topics}, f"「{topic}」門檻 {new:.3f} ")
    if not changed:
        st.caption("拖動上方滑桿試調門檻。")

st.subheader("門檻附近的文章")
st.caption("試調門檻 ±0.02 內的文章，以及因試調而改變入選狀態的文章。")
near = df[((df["score"] - new).abs() <= 0.02) | ((df["score"] >= new) != (df["score"] >= current))]
near = near.sort_values("score", ascending=False)
change = [("新增" if v >= new else "移除") if (v >= new) != (v >= current) else "" for v in near["score"]]
st.dataframe(
    near.assign(star=near["star"].map({True: "★", False: ""}), change=change,
                status=near["score"].map(lambda v: "✓" if v >= new else "")
                )[["score", "status", "change", "star", "title", "journal", "url"]],
    column_config={
        "score": st.column_config.NumberColumn("分數", format="%.3f", width=60),
        "status": st.column_config.TextColumn("入選", width=45),
        "change": st.column_config.TextColumn("變化", width=50),
        "star": st.column_config.TextColumn("★", width=35),
        "title": st.column_config.TextColumn("標題", width="large"),
        "journal": "期刊",
        "url": st.column_config.LinkColumn("連結", display_text="開啟", width=50),
    },
    hide_index=True, width="stretch",
)

st.divider()
st.markdown("**重新計算分數**")
rescore_panel("改過主題描述、新增主題或更換模型後，用目前設定重新計算所有文章的分數，不改變各期入選紀錄。")
