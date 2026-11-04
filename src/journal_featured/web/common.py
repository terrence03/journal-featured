"""Helpers shared by the Streamlit pages."""

import json
import re
from contextlib import closing, contextmanager
from pathlib import Path

import streamlit as st
import yaml
from dotenv import load_dotenv

from journal_featured import lock
from journal_featured.config import ROOT
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


def is_running() -> bool:
    return lock.is_held(data_dir() / lock.NAME)


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>#|$~])")


def md(text: str) -> str:
    """Escape text so titles with brackets, asterisks or $ render literally."""
    return _MD_SPECIAL.sub(r"\\\1", text or "")


def article_card(a: Article, topic: str | None = None) -> None:
    score = a.scores.get(topic, a.score) if topic else a.score
    st.markdown(f"**[{md(a.title)}]({a.url})**" if a.url else f"**{md(a.title)}**")
    meta = [a.journal, a.published, "、".join(a.matches) or a.topic, f"{score:.3f}"]
    st.caption(" ｜ ".join(m for m in meta if m))
    if a.note:
        st.markdown(f"→ {md(a.note)}")
    if a.abstract or a.authors:
        with st.expander("作者與摘要"):
            if a.authors:
                st.caption(md(", ".join(a.authors)))
            st.write(md(a.abstract) or "（無摘要）")


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
