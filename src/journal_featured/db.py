"""SQLite logging: one table for run records, one for every article seen."""

import json
import sqlite3
from pathlib import Path

from .fetch import Article

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    run_at      TEXT NOT NULL,
    since       TEXT NOT NULL,
    until       TEXT NOT NULL,
    counts      TEXT NOT NULL,  -- JSON: {journal: n}
    new_count   INTEGER NOT NULL,
    selected    INTEGER NOT NULL,
    mail_status TEXT NOT NULL,
    errors      TEXT NOT NULL DEFAULT '',
    featured    TEXT            -- JSON: [{doi, reason}] picked by Claude
);
CREATE TABLE IF NOT EXISTS articles (
    doi        TEXT PRIMARY KEY,
    journal    TEXT NOT NULL,
    title      TEXT NOT NULL,
    published  TEXT,
    authors    TEXT,            -- JSON list
    abstract   TEXT,
    url        TEXT,
    topic      TEXT,
    score      REAL,
    selected   INTEGER NOT NULL DEFAULT 0,
    matches    TEXT,            -- JSON list of topics passing their threshold
    scores     TEXT,            -- JSON: {topic: score} for every topic
    note       TEXT,            -- Claude's one-line note
    first_seen TEXT NOT NULL,
    run_id     INTEGER REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS articles_selected ON articles(selected, first_seen);
"""


def _article(row) -> Article:
    doi, journal, title, published, authors, abstract, url, topic, score, selected, matches, scores, note = row
    topic, score = topic or "", score or 0.0
    return Article(doi=doi, journal=journal, title=title, published=published or "",
                   authors=json.loads(authors or "[]"), abstract=abstract or "", url=url or "",
                   topic=topic, score=score, selected=bool(selected),
                   matches=json.loads(matches) if matches else ([topic] if selected else []),
                   scores=json.loads(scores) if scores else ({topic: score} if topic else {}),
                   note=note or "")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30)
        # WAL lets the web page read while a run is writing.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        # Columns added after the first release.
        for table, col in (("articles", "matches"), ("articles", "note"), ("runs", "featured"),
                           ("articles", "scores")):
            cols = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")

    def seen_dois(self) -> set[str]:
        return {row[0] for row in self.conn.execute("SELECT doi FROM articles")}

    def save_run(self, articles: list[Article], run_at: str, since: str, until: str,
                 counts: dict[str, int], selected: int, mail_status: str, errors: list[str],
                 featured: list[tuple[Article, str]] | None = None) -> int:
        with self.conn:
            run_id = self.conn.execute(
                "INSERT INTO runs (run_at, since, until, counts, new_count, selected, mail_status, errors,"
                " featured) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_at, since, until, json.dumps(counts, ensure_ascii=False), len(articles),
                 selected, mail_status, "\n".join(errors),
                 json.dumps([{"doi": a.doi, "reason": r} for a, r in featured or []], ensure_ascii=False)),
            ).lastrowid
            self.conn.executemany(
                "INSERT OR IGNORE INTO articles"
                " (doi, journal, title, published, authors, abstract, url, topic, score, selected, matches,"
                " scores, note, first_seen, run_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(a.doi, a.journal, a.title, a.published, json.dumps(a.authors, ensure_ascii=False),
                  a.abstract, a.url, a.topic, a.score, int(a.selected),
                  json.dumps(a.matches, ensure_ascii=False),
                  json.dumps(a.scores, ensure_ascii=False) if a.scores else None,
                  a.note or None, run_at, run_id)
                 for a in articles],
            )
        return run_id

    def latest_run(self) -> tuple[int, str, str, list[Article]] | None:
        """(run_id, since, until, selected articles) of the most recent run."""
        run = self.conn.execute("SELECT id, since, until FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        if not run:
            return None
        return run[0], run[1], run[2], self.run_articles(run[0])

    def runs(self) -> list[dict]:
        """Every run, newest first, with JSON columns decoded."""
        cur = self.conn.execute(
            "SELECT id, run_at, since, until, counts, new_count, selected, mail_status, errors, featured"
            " FROM runs ORDER BY id DESC")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur]
        for r in rows:
            r["counts"] = json.loads(r["counts"] or "{}")
            r["featured"] = json.loads(r["featured"] or "[]")
        return rows

    def run_articles(self, run_id: int, selected_only: bool = True) -> list[Article]:
        sql = ("SELECT doi, journal, title, published, authors, abstract, url, topic, score, selected,"
               " matches, scores, note FROM articles WHERE run_id = ?")
        if selected_only:
            sql += " AND selected = 1"
        return [_article(row) for row in self.conn.execute(sql, (run_id,))]

    def featured(self, run_id: int, articles: list[Article]) -> list[tuple[Article, str]]:
        """Stored Claude picks for a run, resolved against that run's articles."""
        row = self.conn.execute("SELECT featured FROM runs WHERE id = ?", (run_id,)).fetchone()
        by_doi = {a.doi: a for a in articles}
        return [(by_doi[p["doi"]], p["reason"])
                for p in json.loads(row[0] or "[]") if p["doi"] in by_doi]

    def update_abstracts(self, articles: list[Article]) -> None:
        with self.conn:
            self.conn.executemany("UPDATE articles SET abstract = ? WHERE doi = ?",
                                  [(a.abstract, a.doi) for a in articles if a.abstract])

    def all_articles(self) -> list[Article]:
        return [_article(row) for row in self.conn.execute(
            "SELECT doi, journal, title, published, authors, abstract, url, topic, score, selected,"
            " matches, scores, note FROM articles")]

    def update_scores(self, articles: list[Article]) -> None:
        """Store recomputed per-topic scores; topic/score/matches/selected keep the values of their run."""
        with self.conn:
            self.conn.executemany("UPDATE articles SET scores = ? WHERE doi = ?",
                                  [(json.dumps(a.scores, ensure_ascii=False), a.doi) for a in articles])

    def update_notes(self, articles: list[Article]) -> None:
        with self.conn:
            self.conn.executemany("UPDATE articles SET note = ? WHERE doi = ?",
                                  [(a.note, a.doi) for a in articles if a.note])

    def set_featured(self, run_id: int, featured: list[tuple[Article, str]]) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET featured = ? WHERE id = ?",
                (json.dumps([{"doi": a.doi, "reason": r} for a, r in featured], ensure_ascii=False), run_id),
            )

    def close(self) -> None:
        self.conn.close()
