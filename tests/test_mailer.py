from journal_featured.fetch import Article
from journal_featured.mailer import render


def test_render_escapes_and_lists():
    a = Article(doi="10.1/x", title="<b>Bold</b>", journal="J", published="2026-10-01",
                abstract="abs", url="https://doi.org/10.1/x", topic="A", score=0.88,
                scores={"A": 0.88, "B": 0.84}, matches=["A", "B"])
    html, text = render({"A": [a]}, "2026-10-01", "2026-10-15")
    assert "&lt;b&gt;Bold" in html and "0.88" in html
    assert "[0.88] <b>Bold</b>" in text
    assert "亦屬：B" in html


def test_render_uses_per_topic_score():
    a = Article(doi="10.1/x", title="T", journal="J", published="", abstract="",
                scores={"A": 0.88, "B": 0.84}, matches=["A", "B"], topic="A", score=0.88)
    html, text = render({"A": [a], "B": [a]}, "s", "u")
    assert "[0.88] T" in text and "[0.84] T" in text
    assert "亦屬：A" in html


def test_render_empty():
    html, text = render({}, "a", "b")
    assert "沒有符合" in html and "沒有符合" in text


def test_render_featured_block():
    a = Article(doi="10.1/x", title="Featured", journal="J", published="2026-10-01", abstract="",
                url="https://doi.org/10.1/x", scores={"A": 0.9}, matches=["A"], topic="A", score=0.9)
    html, text = render({"A": [a]}, "s", "u", featured=[(a, "值得一讀的理由")])
    assert "本週精選" in html and "值得一讀的理由" in html
    assert text.index("本週精選") < text.index("## A")


def test_render_note():
    a = Article(doi="10.1/x", title="T", journal="J", published="", abstract="",
                scores={"A": 0.9}, matches=["A"], topic="A", score=0.9, note="一句簡評")
    html, text = render({"A": [a]}, "s", "u")
    assert "→ 一句簡評" in html and "→ 一句簡評" in text
