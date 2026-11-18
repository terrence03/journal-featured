import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from journal_featured.db import Store
from journal_featured.fetch import Article
from journal_featured.web import app


def article(doi, title, matches, score, **kw):
    return Article(doi=doi, title=title, journal=kw.pop("journal", "Energy Policy"), published="2026-11-01",
                   abstract=kw.pop("abstract", "An abstract."), authors=["Ana Lin", "Bo Wu", "Cy Xu", "Di Yu"],
                   url=kw.pop("url", f"https://doi.org/{doi}"), topic=(matches or ["A"])[0], score=score,
                   scores={m: score for m in matches}, matches=matches, selected=bool(matches), **kw)


@pytest.fixture
def config(tmp_path):
    store = Store(tmp_path / "j.db")
    old = article("10.1/old", "Older paper", ["B"], 0.9, journal="Nature Energy")
    store.save_run([old], "2026-11-02 08:00", "2026-10-19", "2026-11-02", {}, 1, "已寄送", [])
    solar = article("10.1/solar", "Solar <b>auctions</b>", ["A", "B"], 0.95, note="談競標制度")
    wind = article("10.1/wind", "Wind siting", ["B"], 0.88, url="javascript:alert(1)")
    pick = article("10.1/pick", "Grid pricing", ["A"], 0.86)
    skipped = article("10.1/skip", "Unrelated paper", [], 0.5)
    store.save_run([solar, wind, pick, skipped], "2026-11-09 08:00", "2026-10-26", "2026-11-09", {}, 3,
                   "已寄送", [], featured=[(pick, "值得一讀")])
    store.close()
    path = tmp_path / "config.yaml"
    path.write_text(f"db_path: {tmp_path / 'j.db'}\ntopics:\n  - {{name: B, description: b}}\n"
                    "  - {name: A, description: a}\n")
    return path


def test_latest_issue_lists_selected_articles(config):
    html = app.render({}, config)
    assert "2026-10-26 ～ 2026-11-09" in html and "最新一期" in html
    # Claude's pick comes first, then by relevance; unselected and other runs' articles are left out.
    assert html.index("Grid pricing") < html.index("Solar") < html.index("Wind siting")
    assert "值得一讀" in html and "談競標制度" in html
    assert "Unrelated paper" not in html and "Older paper" not in html
    assert "Ana Lin, Bo Wu, Cy Xu et al." in html
    assert html.index(">B<span>2<") < html.index(">A<span>2<")  # topic chips in config order
    assert "相似度" not in html and "0.95" not in html


def test_external_text_and_links_are_escaped(config):
    html = app.render({}, config)
    assert "Solar &lt;b&gt;auctions&lt;/b&gt;" in html
    assert "javascript:" not in html


def test_issue_topic_filter_and_older_run(config):
    html = app.render({"topic": "A"}, config)
    assert "Solar" in html and "Grid pricing" in html and "Wind siting" not in html
    older = app.render({"run": "1"}, config)
    assert "Older paper" in older and "最新一期" not in older and "Grid pricing" not in older
    assert "Grid pricing" in app.render({"run": "nope"}, config)  # unknown run: latest


def test_library_search(config):
    everything = app.render({"view": "all"}, config)
    assert "共 4 篇" in everything and "Unrelated paper" not in everything
    assert "值得一讀" in everything
    found = app.render({"view": "all", "q": "wind SITING"}, config)
    assert "共 1 篇" in found and "Wind siting" in found
    by_journal = app.render({"view": "all", "journal": "Nature Energy", "topic": "B"}, config)
    assert "共 1 篇" in by_journal and "Older paper" in by_journal
    assert "找不到符合條件的文章" in app.render({"view": "all", "q": "zzz", "page": "9"}, config)


def test_empty_database(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(f"db_path: {tmp_path / 'j.db'}\n")
    assert "還沒有任何選讀結果" in app.render({}, path)


def test_server_health_and_unknown_files():
    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(f"{base}/any/prefix/healthz") as r:
            assert r.read() == b"ok" and "default-src 'none'" in r.headers["Content-Security-Policy"]
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}/favicon.ico")
        assert e.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
