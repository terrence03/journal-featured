from journal_featured.db import Store
from journal_featured.fetch import Article


def test_save_and_dedupe(tmp_path):
    store = Store(tmp_path / "sub" / "j.db")
    a = Article(doi="10.1/x", title="T", journal="J", published="2026-10-01", abstract="abs",
                authors=["Lin"], topic="A", score=0.9, selected=True,
                matches=["A", "B"])
    run_id = store.save_run([a], "2026-11-03 08:00", "2026-10-20", "2026-11-03", {"J": 1}, 1, "已寄送", [],
                            featured=[(a, "理由")])
    assert store.conn.execute("SELECT featured FROM runs").fetchone()[0] == '[{"doi": "10.1/x", "reason": "理由"}]'
    assert store.seen_dois() == {"10.1/x"}
    # re-saving the same DOI is ignored, not an error
    store.save_run([a], "2026-11-10 08:00", "2026-10-27", "2026-11-10", {"J": 1}, 0, "未寄送", ["x"])
    rows = store.conn.execute("SELECT doi, selected, matches, run_id FROM articles").fetchall()
    assert rows == [("10.1/x", 1, '["A", "B"]', run_id)]
    assert store.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 2


def test_adds_matches_column_to_old_db(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE articles (doi TEXT PRIMARY KEY, journal TEXT NOT NULL, title TEXT NOT NULL,"
                 " published TEXT, authors TEXT, abstract TEXT, url TEXT, topic TEXT, score REAL,"
                 " selected INTEGER NOT NULL DEFAULT 0, first_seen TEXT NOT NULL, run_id INTEGER)")
    conn.close()
    cols = {r[1] for r in Store(path).conn.execute("PRAGMA table_info(articles)")}
    assert "matches" in cols


def test_latest_run_and_featured(tmp_path):
    store = Store(tmp_path / "j.db")
    assert store.latest_run() is None
    a = Article(doi="10.1/x", title="T", journal="J", published="2026-10-01", abstract="",
                topic="A", score=0.9, selected=True, matches=["A", "B"])
    b = Article(doi="10.1/y", title="U", journal="J", published="2026-10-01", abstract="", topic="A", score=0.5)
    run_id = store.save_run([a, b], "r", "2026-10-20", "2026-11-03", {}, 1, "已寄送", [])
    rid, since, until, arts = store.latest_run()
    assert (rid, since, until) == (run_id, "2026-10-20", "2026-11-03")
    assert [(x.doi, x.matches) for x in arts] == [("10.1/x", ["A", "B"])]  # selected only
    arts[0].abstract = "filled"
    store.update_abstracts(arts)
    arts[0].note = "簡評"
    store.update_notes(arts)
    assert store.latest_run()[3][0].note == "簡評"
    store.set_featured(run_id, [(arts[0], "理由")])
    assert store.conn.execute("SELECT abstract FROM articles WHERE doi='10.1/x'").fetchone()[0] == "filled"
    assert "理由" in store.conn.execute("SELECT featured FROM runs").fetchone()[0]
    assert [(x.doi, r) for x, r in store.featured(run_id, arts)] == [("10.1/x", "理由")]


def test_runs_and_scores_roundtrip(tmp_path):
    store = Store(tmp_path / "j.db")
    a = Article(doi="10.1/x", title="T", journal="J", published="2026-10-01", abstract="",
                topic="A", score=0.9, scores={"A": 0.9, "B": 0.8}, selected=True, matches=["A"])
    b = Article(doi="10.1/y", title="U", journal="J", published="2026-10-01", abstract="", topic="B", score=0.5)
    run_id = store.save_run([a, b], "r", "2026-10-20", "2026-11-03", {"J": 2}, 1, "已寄送", [],
                            featured=[(a, "理由")])
    [run] = store.runs()
    assert run["id"] == run_id and run["counts"] == {"J": 2}
    assert run["featured"] == [{"doi": "10.1/x", "reason": "理由"}]
    [sel] = store.run_articles(run_id)
    assert sel.scores == {"A": 0.9, "B": 0.8}
    every = store.run_articles(run_id, selected_only=False)
    assert {x.doi: x.matches for x in every} == {"10.1/x": ["A"], "10.1/y": []}
    assert {x.doi: x.scores for x in every}["10.1/y"] == {"B": 0.5}  # pre-scores rows fall back to best topic

