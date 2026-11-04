import pandas as pd
import streamlit as st

from journal_featured.web.common import raw_config, store

st.title("執行紀錄")

with store() as s:
    runs = s.runs()
if not runs:
    st.info("尚無執行紀錄。")
    st.stop()

# Journals that returned nothing (or failed) in each of the last 3 runs: ISSN may be wrong or retired.
recent = runs[:3]
if len(recent) >= 2:
    for j in raw_config().get("journals", []):
        if all(not r["counts"].get(j["name"]) for r in recent):
            st.warning(f"「{j['name']}」最近 {len(recent)} 次都抓到 0 篇或抓取失敗，請確認 ISSN（{j.get('issn') or '未設定'}）",
                       icon=":material/warning:")

st.dataframe(
    pd.DataFrame([{
        "執行時間": r["run_at"], "區間": f"{r['since']} ~ {r['until']}", "新文章": r["new_count"],
        "入選": r["selected"], "精選": len(r["featured"]), "寄送": r["mail_status"],
        "錯誤": r["errors"].splitlines()[0] if r["errors"] else "",
    } for r in runs]),
    hide_index=True, width="stretch",
)

st.subheader("各期刊抓取數")
st.caption("最近 12 次執行；— 表示該次抓取失敗或當時未設定此期刊。紅色為 0 篇。")
shown = list(reversed(runs[:12]))
names = [j["name"] for j in raw_config().get("journals", [])]
names += sorted({n for r in shown for n in r["counts"]} - set(names))
counts = pd.DataFrame(
    {r["until"] + ("" if i == 0 or shown[i - 1]["until"] != r["until"] else f" #{r['id']}"):
         [r["counts"].get(n) for n in names] for i, r in enumerate(shown)},
    index=names,
).astype("Int64")
st.dataframe(
    counts.style.map(lambda v: "color: #d93025; font-weight: 600" if v == 0 else "")
          .format(lambda v: "—" if pd.isna(v) else str(v)),
    width="stretch",
)

with_errors = [r for r in runs if r["errors"]]
if with_errors:
    st.subheader("錯誤明細")
    for r in with_errors:
        with st.expander(f"{r['run_at']}（{r['since']} ~ {r['until']}）"):
            st.code(r["errors"], language=None)
