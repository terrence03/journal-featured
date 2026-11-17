from journal_featured.fetch import normalize_doi, parse_work, rebuild_abstract, strip_jats


def test_rebuild_abstract_orders_words():
    assert rebuild_abstract({"world": [1], "hello": [0], "again": [2]}) == "hello world again"
    assert rebuild_abstract(None) == ""


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1038/ABC") == "10.1038/abc"
    assert normalize_doi(None) == ""


def test_strip_jats():
    assert strip_jats("<jats:p>A &amp; B</jats:p>") == "A & B"


def test_parse_work():
    w = {
        "doi": "https://doi.org/10.1/x",
        "title": "T",
        "publication_date": "2026-10-01",
        "abstract_inverted_index": {"abc": [0]},
        "authorships": [{"author": {"display_name": "Lin"}}],
        "primary_location": {"landing_page_url": "https://example.org/x"},
    }
    a = parse_work(w, "J")
    assert (a.doi, a.abstract, a.authors, a.url) == ("10.1/x", "abc", ["Lin"], "https://example.org/x")
    assert parse_work({**w, "doi": None}, "J") is None


def test_parse_work_skips_notices():
    w = {"doi": "10.1/x", "title": "Author Correction: Something"}
    assert parse_work(w, "J") is None
    assert parse_work({"doi": "10.1/y", "title": "Real paper", "type": "erratum"}, "J") is None
    assert parse_work({"doi": "10.1/z", "title": "Correctional facilities and health"}, "J") is not None


def _response(status, url):
    import requests
    r = requests.Response()
    r.status_code, r.url, r.reason = status, url, "Forbidden"
    return r


def test_failed_request_does_not_leak_api_key(monkeypatch, caplog):
    import logging

    import pytest

    from journal_featured import fetch

    url = "https://api.openalex.org/works?filter=x&api_key=SECRET123&cursor=*"
    monkeypatch.setattr(fetch._session, "get", lambda *a, **k: _response(403, url))
    with pytest.raises(fetch.FetchError) as exc:
        fetch.fetch_journal("1234-5678", "J", __import__("datetime").date(2026, 1, 1), "SECRET123")
    assert "SECRET123" not in str(exc.value) and "api_key=***" in str(exc.value)
    assert exc.value.__suppress_context__  # the original exception (with the URL) is not printed

    # Retried failures are logged too.
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)

    def boom(*a, **k):
        import requests
        raise requests.ConnectionError("Max retries exceeded with url: /works?api_key=SECRET123 (Caused by x)")

    monkeypatch.setattr(fetch._session, "get", boom)
    with caplog.at_level(logging.WARNING), pytest.raises(fetch.FetchError):
        fetch._get("https://api.openalex.org/works", {"api_key": "SECRET123"})
    assert caplog.records and "SECRET123" not in caplog.text


def test_meta_abstract():
    from journal_featured.fetch import meta_abstract

    page = ('<meta name="description" content="site blurb">'
            "<meta content='A &amp; B' name='dc.description' />")
    assert meta_abstract(page) == "A &amp; B"
    assert meta_abstract('<meta name="description" content="site blurb">') == ""


def test_fill_abstract_sources(monkeypatch):
    from journal_featured import fetch

    calls = []

    def source(name, value):
        def f(doi, *a):
            calls.append(name)
            return value
        return f

    monkeypatch.setattr(fetch, "_crossref_abstract", source("crossref", ""))
    monkeypatch.setattr(fetch, "_landing_abstract", source("landing", "Abstract  From &amp; <b>page</b>"))

    def filled(doi):
        calls.clear()
        a = fetch.Article(doi=doi, title="T", journal="J", published="", abstract="")
        fetch.fill_abstract(a)
        return a.abstract, list(calls)

    assert filled("10.1016/j.x") == ("", ["crossref"])  # ScienceDirect pages can't be fetched
    assert filled("10.1038/x") == ("From & page", ["crossref", "landing"])
