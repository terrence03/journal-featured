"""Helpers shared by the Streamlit pages."""

import json
import re
from contextlib import closing, contextmanager
from pathlib import Path

import streamlit as st
import yaml
from dotenv import load_dotenv

from journal_featured import lock
from journal_featured.config import ROOT, ConfigError, save_raw
from journal_featured.db import Store
from journal_featured.fetch import Article

CONFIG = ROOT / "config.yaml"
load_dotenv(ROOT / ".env")


def raw_config() -> dict:
    return yaml.safe_load(CONFIG.read_text()) or {}


def data_dir() -> Path:
    return (ROOT / raw_config().get("db_path", "data/journal.db")).parent


@contextmanager
def store():
    with closing(Store(ROOT / raw_config().get("db_path", "data/journal.db"))) as s:
        yield s


def backup_dir() -> Path:
    return data_dir() / "config-backups"


def save_config(updates: dict, label: str, replace: bool = False) -> bool:
    """Merge `updates` into config.yaml (or replace it wholesale), backing up the old version.

    On success the page reruns and shows the message via show_saved().
    """
    new = dict(updates) if replace else dict(raw_config(), **updates)
    try:
        backup = save_raw(new, CONFIG, backup_dir())
    except ConfigError as e:
        st.error(f"未儲存：{e}", icon=":material/error:")
        return False
    st.session_state["saved"] = f"{label}已儲存" + (f"（備份：{backup.name}）" if backup else "")
    st.rerun()
    return True


def show_saved() -> None:
    if msg := st.session_state.pop("saved", None):
        st.toast(msg, icon=":material/check_circle:")


def topic_threshold(raw: dict, name: str) -> float:
    t = next((t for t in raw.get("topics") or [] if t.get("name") == name), {})
    return float(t["threshold"] if t.get("threshold") is not None else raw.get("threshold", 0.85))


def is_running() -> bool:
    return lock.is_held(data_dir() / lock.NAME)


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>#|$~])")


def md(text: str) -> str:
    """Escape text so titles with brackets, asterisks or $ render literally."""
    return _MD_SPECIAL.sub(r"\\\1", text or "")


def starred() -> set[str]:
    with store() as s:
        return s.starred()


def _toggle_star(doi: str, on: bool) -> None:
    with store() as s:
        s.set_star(doi, on)


def star_button(doi: str, on: bool, key: str) -> None:
    st.button("★" if on else "☆", key=f"star-{key}-{doi}", type="tertiary",
              help="取消收藏" if on else "加入收藏", on_click=_toggle_star, args=(doi, not on))


def article_card(a: Article, topic: str | None = None, *, starred: bool = False, key: str = "") -> None:
    """One article: title + star, meta line, Claude's note, details on demand.

    Under a topic tab, the other topics it also matches are shown as「亦屬」.
    """
    with st.container(horizontal=True, vertical_alignment="top", gap="small", wrap=False):
        st.markdown(f"**[{md(a.title)}]({a.url})**" if a.url else f"**{md(a.title)}**", width="stretch")
        star_button(a.doi, starred, key)
    others = [m for m in a.matches if m != topic] if topic else a.matches
    topics = ("亦屬：" if topic else "") + "、".join(others) if others else ""
    st.caption(" ｜ ".join(m for m in [a.journal, a.published, topics] if m))
    if a.note:
        st.markdown(f"→ {md(a.note)}")
    with st.expander("摘要與詳細資料"):
        if a.authors:
            st.caption(md(", ".join(a.authors)))
        st.write(md(a.abstract) or "（無摘要）")
        if a.scores:
            ranked = sorted(a.scores.items(), key=lambda kv: kv[1], reverse=True)
            st.caption("相似度：" + " · ".join(f"{md(t)} {v:.3f}" for t, v in ranked))


def bibtex(rows: list[dict]) -> str:
    """BibTeX entries for article rows (articles table columns)."""
    entries, used = [], set()
    for r in rows:
        authors = json.loads(r.get("authors") or "[]")
        year = (r.get("published") or "")[:4]
        last = authors[0].split()[-1] if authors else "anon"
        word = next((w for w in re.findall(r"\w+", r["title"]) if len(w) > 3), "")
        key = re.sub(r"\W", "", f"{last}{year}{word}").lower() or "article"
        base, n = key, 1
        while key in used:
            n += 1
            key = f"{base}{chr(ord('a') + n - 2)}"
        used.add(key)
        fields = {
            "title": r["title"], "author": " and ".join(authors), "journal": r["journal"],
            "year": year, "doi": r["doi"], "url": r.get("url") or "",
        }
        body = ",\n".join(f"  {k} = {{{v.replace('{', '').replace('}', '')}}}" for k, v in fields.items() if v)
        entries.append(f"@article{{{key},\n{body}\n}}")
    return "\n\n".join(entries) + "\n"
